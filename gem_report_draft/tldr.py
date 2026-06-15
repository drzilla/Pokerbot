"""TL;DR section, leak watchlist, and legend emitters."""

from gem_report_draft import _state
from gem_report_draft._helpers import (_wilson_ci, _clr, _clr_min, _clr_naive,
    _pctc, _stat_signal, _verdict_ci, _verdict_pct, _hand_ref, _hand_ref_short,
    _xref, _stat_row, _stat_row_pct, _aim_lookup_from_watchlist, _back_to_kpis,
    _compact_range, _run_emoji, _outcome_label, _CI_Z_DEFAULT, _MIN_N_FOR_SIGNAL,
    _RANK_ORD, _break_at_sentences, _href, _emit_correct_ranges)
from gem_report_draft._html import (Doc, _card_html, _cards_html,
    _cards_str_to_pills, _cards_text_to_pills, _md_inline, _html_escape,
    _sort_cards_desc, _describe_made_hand, _SUIT_HTML, _RANK_VALUES, _SUIT_VALUES)
from gem_report_draft._blocks import financial_table_block
from gem_report_draft._hand_grid import (_render_hand_grid_table,
    _key_decision_action_class, _pick_key_action_idx, _hero_actions_by_street_from_app,
    _hero_action_verbs_by_street_from_app)
from gem_report_draft.sections_financial import _build_daily_pnl_table, _fmt_usd

import gem_made_hands as mh


# ============================================================
# OPENING DASHBOARD — data-driven card layout replacing
# the bullet-heavy TL;DR prose. All content is computed from
# s (stats) and rd (report_data); nothing is hard-coded.
# ============================================================

def _dashboard_status(bb100, true_ev, n_punts, total_var):
    """Hero status pill: emoji, text, CSS class suffix."""
    if bb100 > 0 and true_ev > 0 and n_punts == 0:
        return '🟢', 'Winning process', 'green'
    if bb100 < 0 and true_ev > 0 and n_punts <= 1:
        return '🟢', 'Good decisions, bad runout', 'green'
    if abs(total_var) > 5 and abs(true_ev) < 3:
        return '⚪', 'Variance session', 'neutral'
    if true_ev >= -1 and true_ev <= 5 and n_punts >= 2:
        return '🟡', 'Work to do', 'amber'
    if true_ev < -1 and n_punts >= 3:
        return '🔴', 'Leak session', 'red'
    if true_ev > 5:
        return '🟢', 'Strong process', 'green'
    if true_ev < -1:
        return '🟡', 'Below baseline', 'amber'
    return '⚪', 'Mixed signals', 'neutral'


def _dashboard_headline(bb100, true_ev, total_var):
    """Hero headline text — dynamic based on result vs true EV."""
    if bb100 > 5 and true_ev > 5:
        if total_var < -3:
            return 'Good poker, variance tax.'
        return 'Clicking. Process AND result.'
    if bb100 > 5 and 1 <= true_ev <= 5:
        return 'Decent session, result ran a bit ahead.'
    if -1 <= bb100 <= 5 and true_ev > 5:
        return 'Session was fine, result just doesn’t show it.'
    if bb100 < -1 and true_ev > 0:
        return 'The result lies. Your process was good.'
    if bb100 < -1 and true_ev < -1:
        return 'Tough session. Honest feedback below.'
    return 'Mixed signals this session.'


def _dashboard_subtitle(bb100, true_ev, total_var, n_punts, n_mist, dt):
    """Hero subtitle — plain-English interpretation."""
    disc_label = (dt.get('label', '') or '').lower() if dt else ''
    parts = []
    if true_ev > 5:
        parts.append(f'True EV was strong at {true_ev:+.1f} bb/100')
    elif true_ev > 0:
        parts.append(f'True EV was positive at {true_ev:+.1f} bb/100')
    else:
        parts.append(f'True EV came in at {true_ev:+.1f} bb/100')
    if abs(total_var) >= 3:
        direction = 'negative' if total_var < 0 else 'positive'
        parts.append(f'Variance was {direction} ({total_var:+.1f} bb/100)')
    if n_punts == 0:
        parts.append('Zero punts')
    elif n_punts <= 2:
        parts.append(f'{n_punts} punt{"s" if n_punts != 1 else ""}')
    else:
        parts.append(f'{n_punts} punts flagged')
    if 'elite' in disc_label:
        parts.append('Discipline was elite')
    elif disc_label:
        parts.append(f'Discipline: {disc_label}')
    return '. '.join(parts[:3]) + '.'


def _dashboard_beliefs(bb100, true_ev, total_var, n_punts, ra):
    """Belief cards: (believe_text, dont_overreact_text)."""
    # BELIEVE THIS
    if true_ev > 0 and n_punts <= 1:
        believe = (f'You played a {"winning" if bb100 > 0 else "solid"} session: '
                   f'{bb100:+.1f} actual bb/100 and {true_ev:+.1f} '
                   f'var-adjusted true EV.')
    elif true_ev > 0:
        believe = (f'Your True EV was positive ({true_ev:+.1f}), '
                   f'which means the core play was sound despite {n_punts} punts.')
    else:
        believe = (f'True EV came in at {true_ev:+.1f} bb/100. '
                   f'The areas that cost EV are identified below — '
                   f'they are fixable.')

    # DO NOT OVERREACT
    if abs(total_var) >= 3 and n_punts <= 1:
        # Variance dominated, few punts
        var_components = []
        if ra:
            mh_v = ra.get('made_hands_var_per_100', 0)
            eai_v = ra.get('eai_variance_per_100', 0)
            if abs(mh_v) >= 1:
                var_components.append('made-hand runout')
            if abs(eai_v) >= 1:
                var_components.append('all-in EV')
        var_str = ' and '.join(var_components) if var_components else 'variance layers'
        dont = (f'The result was shaped by {var_str}, '
                f'not by punts ({total_var:+.1f} bb/100 total variance).')
    elif n_punts == 0 and bb100 < 0:
        dont = ('A losing result with zero punts is textbook variance. '
                'The process was clean.')
    elif n_punts >= 3:
        dont = (f'{n_punts} punts is above normal. '
                f'Focus on the patterns, not the result.')
    else:
        dont = ('Small sample — one session doesn’t redefine your skill level. '
                'Trust the multi-session trend.')
    return believe, dont


def _dashboard_variance_rows(ra):
    """Build variance component rows sorted by abs impact."""
    if not ra:
        return []
    rows = []
    for key, label, detail_neg, detail_pos, anchor in [
        ('made_hands_var_per_100', 'Made hands',
         'Boards did not complete enough value hands',
         'Boards cooperated — made hands above expectation', 'sec-1-6'),
        ('card_quality_var_per_100', 'Starting-card quality',
         'Received fewer premium / playable starting hands',
         'Received enough playable / premium starting hands', 'sec-1-5'),
        ('eai_variance_per_100', 'All-in EV',
         'Lost more all-ins than expectation',
         'Won more all-ins than expectation', 'sec-1-4'),
        ('cooler_var_per_100', 'Cooler frequency',
         'Coolered more than expected',
         'Cooled less than expected', 'sec-1-7'),
    ]:
        val = ra.get(key, 0)
        if abs(val) < 0.3:
            continue
        emoji = '\U0001f525' if val > 0 else '\U0001f976'
        detail = detail_pos if val > 0 else detail_neg
        cls = 'od-vr-good' if val > 0 else 'od-vr-bad'
        rows.append((abs(val), emoji, label, detail, val, cls, anchor))
    rows.sort(key=lambda r: -r[0])
    return rows


def _dashboard_fix_items(s, rd, analyst):
    """Build the 'what to fix next session' items from measured leaks."""
    items = []
    # 1. III.2 synthesis leaks (metric-confirmed)
    _synth = (analyst.get('__synthesis__', {}) or {})
    _leaks = _synth.get('leaks', {}) if isinstance(_synth, dict) else {}
    for leak_name, meta in _leaks.items():
        if not isinstance(meta, dict):
            continue
        judgment = meta.get('judgment', '')
        # Extract BB/100 from judgment text if available
        import re as _re_fix
        bb_match = _re_fix.search(r'([+-]?\d+\.?\d*)\s*BB/100', judgment)
        bb100_est = float(bb_match.group(1)) if bb_match else None
        # Human-readable name from the key
        name = leak_name.replace('_', ' ').title()
        direction = meta.get('direction', '')
        # Collect hand IDs from leak examples for popup drill-down
        _fix_hids = []
        for _ex in (meta.get('examples') or []):
            _eid = _ex.get('hand_id', _ex) if isinstance(_ex, dict) else str(_ex)
            if isinstance(_eid, str) and _eid.startswith('TM'):
                _fix_hids.append(_eid[-8:])
        items.append({
            'name': name,
            'detail': _trunc_text(judgment, 200) if judgment else direction,
            'bb100': bb100_est,
            'color': 'amber',
            'section_link': 'sec-3',
            'hand_ids': _fix_hids[:20],
        })
    # 2. MDA missed exploits
    mda_missed = (s.get('mda_exploits', {}) or {}).get('missed', []) or []
    _mda_rejected = {hid for hid, c in analyst.items()
                     if isinstance(c, dict) and c.get('mda_review') == 'rejected'}
    mda_valid = [m for m in mda_missed
                 if isinstance(m, dict) and (m.get('hand_id') or '') not in _mda_rejected]
    if mda_valid:
        total_ev = sum((m.get('ev_bb') or 0) for m in mda_valid)
        n_h = s.get('volume', {}).get('hands', 0) or 1
        ev_per_100 = (total_ev / n_h) * 100
        items.append({
            'name': f'Missed MDA exploits ({len(mda_valid)} hands)',
            'detail': f'{ev_per_100:+.2f} BB/100 estimated upside. '
                      f'Hero diverged from population recommendation.',
            'bb100': ev_per_100,
            'color': 'amber',
            'section_link': 'sec-12',  # FEAT-2: link to MDA section
        })
    # 3. Sizing precision
    _sc = s.get('sizing_consistency', {}) or {}
    _i3 = s.get('ip_3bet_sizing', {}) or {}
    _geo = _sc.get('geometric_pct')
    _dev = _i3.get('deviation_rate_pct')
    if (_geo is not None and _geo < 70) or (_dev is not None and _dev > 15):
        detail_parts = []
        if _geo is not None and _geo < 70:
            detail_parts.append(f'Geometric c-bet compliance {_geo:.0f}% (target ≥70%)')
        if _dev is not None and _dev > 15:
            detail_parts.append(f'IP 3-bet sizing {_dev:.0f}% off target')
        items.append({
            'name': 'Sizing precision',
            'detail': '. '.join(detail_parts),
            'bb100': None,
            'color': 'blue',
        })
    # 4. Persistence leaks (recurring)
    persistence = (rd.get('leak_persistence', {}) or {}).get('current_leaks', []) or []
    for leak in persistence[:2]:
        if not isinstance(leak, dict):
            continue
        name = leak.get('name', leak.get('leak', '—'))
        ev = leak.get('ev_cost_per_100', 0) or leak.get('ev_per_100', 0)
        sessions = leak.get('sessions_seen', 0)
        items.append({
            'name': f'Recurring: {name}',
            'detail': f'{ev:+.2f} BB/100 cost over {sessions} session(s)',
            'bb100': ev,
            'color': 'purple',
        })
    # Sort by abs impact
    items.sort(key=lambda x: -abs(x.get('bb100') or 0))
    return items[:4]


# ── v8.14.0 Slice C: Compact Hand Review Queue ─────────────────────────────
# Priority bucket order is product-facing and fixed (spec §5.2 / §11.3):
# punts -> analyst mistakes -> known-leak examples -> auto-clear mistakes ->
# marginal candidates.
_REVIEW_QUEUE_BUCKETS = ('punt', 'analyst_mistake', 'known_leak',
                         'auto_clear', 'marginal')
_REVIEW_QUEUE_BUCKET_LABEL = {
    'punt': 'Punt',
    'analyst_mistake': 'Analyst mistake',
    'known_leak': 'Known leak',
    'auto_clear': 'Auto clear',
    'marginal': 'Marginal',
}
# UI label -> canonical status (spec §5.5/§6). "Ignore" is intentionally absent.
_REVIEW_STATUS_NORMALIZE = {
    'agree': 'agree', 'debate': 'debate',
    'report bug': 'report_bug', 'report_bug': 'report_bug', 'bug': 'report_bug',
    'drill': 'drill', 'rulebook': 'rulebook',
    'clear': '', '': '', 'none': '', 'null': '',
}
# Follow-up statuses (everything that is a marked status other than agree).
_REVIEW_FOLLOWUP_STATUSES = ('debate', 'report_bug', 'drill', 'rulebook')


def normalize_review_status(label):
    """Map a UI status label to its canonical value. 'Clear'/empty -> ''.
    'Ignore' is NOT a valid user-facing status and normalizes to '' (rejected)."""
    if label is None:
        return ''
    return _REVIEW_STATUS_NORMALIZE.get(str(label).strip().lower(), '')


def build_review_queue(s, rd, analyst, hands_by_id):
    """v8.14.0 Slice C: prioritized compact review queue. PURE + testable.

    Returns the full ordered list of queue items (the JS handles top-N). Each
    item: {id, rank, bucket, reason_label, title, net, cards}. Deterministic
    order: bucket priority -> -abs(net BB) -> hand id. Uses ONLY existing
    prepared data; degrades gracefully when a source is missing (a hand with no
    net/cards still appears with id + reason + title)."""
    analyst = analyst or {}
    hands_by_id = hands_by_id or {}
    seen, items = set(), []

    def _add(hid, bucket, title):
        if not hid or hid in seen:
            return
        seen.add(hid)
        h = hands_by_id.get(hid, {}) or {}
        items.append({
            'id': hid, 'bucket': bucket,
            'reason_label': _REVIEW_QUEUE_BUCKET_LABEL[bucket],
            'title': (title or '').strip(),
            'net': h.get('net_bb', 0) or 0,
            'cards': ''.join(h.get('cards', []) or []),
        })

    # 1. punts (analyst III.1) ; 2. analyst mistakes (analyst III.2)
    for _vp, _bucket, _fallback in (('III.1', 'punt', 'Punt — review first.'),
                                    ('III.2', 'analyst_mistake', 'Strategic leak.')):
        for hid, cmt in analyst.items():
            if (isinstance(cmt, dict) and str(hid).startswith('TM')
                    and (cmt.get('verdict', '') or '').startswith(_vp)):
                _add(hid, _bucket, cmt.get('hand_strength', '') or _fallback)
    # 3. known-leak examples (Issue Explorer)
    for iss in (rd.get('issue_explorer_issues') or rd.get('issue_explorer') or []):
        if not isinstance(iss, dict):
            continue
        _nm = iss.get('name') or iss.get('title') or 'Known-leak example'
        for hid in (iss.get('all_hand_ids') or iss.get('hand_ids') or []):
            if str(hid).startswith('TM'):
                _add(hid, 'known_leak', _nm)
    # 4. auto-clear hands (detector-flagged, auto-resolved). v8.14.1 hotfix
    # (#4): NEVER title these "mistake" — a detector flag that auto-cleared is
    # not a confirmed mistake (the real queue had +7.5BB / +1.8BB / -0.1BB hands
    # all titled "Auto-flagged mistake."). Use a neutral, non-accusatory title;
    # the detector detail is still available inside the hand modal.
    for m in (s.get('mistakes', []) or []):
        _add(m.get('id', ''), 'auto_clear', 'Auto-cleared — quick scan, no analyst action needed.')
    # 5. marginal candidates (needs-review + read-dependent screens)
    for m in ((rd.get('reviewed_mistakes') or {}).get('needs_review') or []):
        _add(m.get('id', ''), 'marginal', m.get('reason', '') or 'Marginal candidate.')
    for c in (rd.get('read_dependent_screen') or []):
        if isinstance(c, dict):
            _add(c.get('id', ''), 'marginal', 'Read-dependent call.')

    _order = {b: i for i, b in enumerate(_REVIEW_QUEUE_BUCKETS)}
    items.sort(key=lambda x: (_order[x['bucket']], -abs(x['net']), x['id']))
    for i, it in enumerate(items, 1):
        it['rank'] = i
    return items


def _dashboard_hands_to_open(s, rd, analyst, hands_by_id):
    """Compatibility shim — the prioritized review queue (full list)."""
    return build_review_queue(s, rd, analyst, hands_by_id)


def _dashboard_cooler_summary(s, rd, analyst):
    """Cooler / large-loss summary for the dashboard."""
    coolers = rd.get('coolers') or s.get('coolers', {}).get('hands', []) or []
    i7_analyst = [(h, c) for h, c in analyst.items()
                  if isinstance(c, dict) and (c.get('verdict', '') or '').startswith('I.7')
                  and h.startswith('TM')]
    cooler_ids = set()
    for c in coolers:
        cid = c.get('id') if isinstance(c, dict) else None
        if cid:
            cooler_ids.add(cid)
    for hid, _ in i7_analyst:
        cooler_ids.add(hid)
    n_coolers = len(cooler_ids)

    # Big losses not classified
    all_classified = set()
    for hid, cmt in analyst.items():
        if isinstance(cmt, dict) and hid.startswith('TM'):
            all_classified.add(hid)
    all_classified |= cooler_ids
    hands_by_id = s.get('_hands_by_id', {}) or {}
    big_unclass = [h for h in hands_by_id.values()
                   if h.get('net_bb', 0) < -25 and h.get('id') not in all_classified]
    return n_coolers, len(big_unclass), sorted(cooler_ids)


def _dashboard_watchlist_items(s, rd):
    """Coach watchlist items from leak_watchlist or promoted leaks."""
    items = []
    wl = rd.get('leak_watchlist')
    if wl and wl.get('top_actions'):
        for a in wl['top_actions'][:4]:
            items.append({
                'name': a.get('label', a.get('metric', '—')),
                'desc': a.get('action', ''),
                'section': a.get('section', ''),
            })
    if not items:
        promoted = (rd.get('leak_persistence', {}) or {}).get('current_leaks', []) or []
        for leak in promoted[:4]:
            if isinstance(leak, dict):
                items.append({
                    'name': leak.get('name', leak.get('leak', '—')),
                    'desc': leak.get('action', leak.get('detail', '')),
                })
    return items[:4]


def _dashboard_drill_items(s, rd):
    """Pre-session drill script — auto-generated from top leaks.

    Produces up to 3 GTOW drill suggestions based on the session's red
    watchlist metrics. Each drill has a name (clickable → copies the GTOW
    search string to clipboard) and a reason.
    """
    drills = []
    # From explicit coaching_rules or drill_script (manual override)
    ds = rd.get('drill_script') or rd.get('pre_session_drills') or []
    if isinstance(ds, list):
        for d in ds[:5]:
            if isinstance(d, str):
                drills.append({'name': d, 'copy': '', 'reason': ''})
            elif isinstance(d, dict):
                drills.append({'name': d.get('text', d.get('drill', '')),
                               'copy': d.get('copy', ''), 'reason': ''})
    # Auto-generate from red watchlist metrics when no manual drills
    if not drills:
        wl = rd.get('leak_watchlist') or {}
        red_items = [a for a in (wl.get('top_actions') or [])
                     if a.get('status') == 'red'][:3]
        # Generate actual GTOW drill JSON from gem_drill_export
        try:
            from gem_drill_export import (Drill, depth_to_str, make_drill_name,
                                          build_description, assemble_tags,
                                          RANGE_ALL)
            _drill_ok = True
        except ImportError:
            _drill_ok = False

        def _make_drill(metric_key):
            """Build a Drill object for a red watchlist metric."""
            if not _drill_ok:
                return None
            _d25 = depth_to_str(25)
            _d30 = depth_to_str(30)
            _gt = 'MTTGeneral'
            _recipes = {
                'CR_Flop_Pct': Drill(
                    name=make_drill_name('Check-raise flop defense',
                        fh_start_spot='flop', depth_str=_d25, gametype=_gt,
                        pot_type='SRP', pos_or_players='BB-HU'),
                    description=build_description(
                        'BB vs BTN/CO SRP flop, practice x/r spots',
                        'Check-raise 8-12% of flop opportunities',
                        'CR flop rate too low this session'),
                    fh_hero='BB', fh_opponent='BTN,CO',
                    depth=_d25, gametype=_gt,
                    fh_start_spot='flop', fh_trainer_mode='stop_end_of_street',
                    fh_groups=RANGE_ALL),
                'VPIP_PFR_Gap_Raw': Drill(
                    name=make_drill_name('3-bet or fold vs open (no flat)',
                        fh_start_spot='preflop', depth_str=_d30, gametype=_gt,
                        pot_type='SRP', pos_or_players='IP'),
                    description=build_description(
                        'Facing open from EP/MP/LP, decide 3-bet or fold',
                        'VPIP-PFR gap under 5pp',
                        'Gap too wide from cold-calling'),
                    fh_hero='CO,BTN,HJ', fh_opponent='UTG,UTG+1,LJ,HJ,CO',
                    depth=_d30, gametype=_gt,
                    fh_start_spot='preflop', fh_groups=RANGE_ALL),
                'ThreeBet_OOP': Drill(
                    name=make_drill_name('3-bet from blinds vs LP opens',
                        fh_start_spot='preflop', depth_str=_d25, gametype=_gt,
                        pot_type='SRP', pos_or_players='Blinds'),
                    description=build_description(
                        'BB/SB vs CO/BTN open, 25bb, 3-bet range',
                        '3-bet OOP 8-10%',
                        '3-bet OOP too low'),
                    fh_hero='BB,SB', fh_opponent='CO,BTN',
                    depth=_d25, gametype=_gt,
                    fh_start_spot='preflop', fh_groups=RANGE_ALL),
                'Cold_Call_NB': Drill(
                    name=make_drill_name('3-bet or fold (cut cold-calls)',
                        fh_start_spot='preflop', depth_str=_d30, gametype=_gt,
                        pot_type='SRP', pos_or_players='IP'),
                    description=build_description(
                        'Facing open IP, practice 3-bet-or-fold discipline',
                        'Cold-call rate under 4%',
                        'Cold-call rate too high'),
                    fh_hero='BTN,CO,HJ', fh_opponent='UTG,UTG+1,LJ',
                    depth=_d30, gametype=_gt,
                    fh_start_spot='preflop', fh_groups=RANGE_ALL),
                'VPIP': Drill(
                    name=make_drill_name('Open-raise first-in ranges',
                        fh_start_spot='preflop', depth_str=_d25, gametype=_gt,
                        pot_type='-', pos_or_players='All'),
                    description=build_description(
                        'All positions, first-in open-raise decisions',
                        'VPIP 21-23%',
                        'VPIP too high — tighten ranges'),
                    depth=_d25, gametype=_gt,
                    fh_start_spot='preflop', fh_groups=RANGE_ALL),
                'AF': Drill(
                    name=make_drill_name('Flop bet-or-check as PFR',
                        fh_start_spot='flop', depth_str=_d25, gametype=_gt,
                        pot_type='SRP', pos_or_players='IP-PFR'),
                    description=build_description(
                        'SRP IP as PFR, flop bet-or-check decision',
                        'AF 2.0-3.0',
                        'AF too low — bet/raise more'),
                    fh_hero='BTN,CO', fh_opponent='BB,SB',
                    depth=_d25, gametype=_gt,
                    fh_start_spot='flop', fh_trainer_mode='stop_end_of_street',
                    fh_groups=RANGE_ALL),
                'F2_Flop_CBet_Small': Drill(
                    name=make_drill_name('Small c-bet sizing flop',
                        fh_start_spot='flop', depth_str=_d25, gametype=_gt,
                        pot_type='SRP', pos_or_players='BTN-BB'),
                    description=build_description(
                        'BTN vs BB SRP, practice 33% flop c-bet',
                        'Small c-bet 50-65%',
                        'Small c-bet too low'),
                    fh_hero='BTN', fh_opponent='BB',
                    depth=_d25, gametype=_gt,
                    fh_start_spot='flop', fh_trainer_mode='stop_end_of_street',
                    fh_groups=RANGE_ALL),
                'CBet_3BP': Drill(
                    name=make_drill_name('C-bet in 3-bet pots',
                        fh_start_spot='flop', depth_str=_d25, gametype=_gt,
                        pot_type='3BP', pos_or_players='IP'),
                    description=build_description(
                        '3BP IP flop, c-bet as 3-bettor',
                        'C-bet 3BP 20-30%',
                        'C-bet 3BP too low'),
                    fh_hero='BTN,CO', fh_opponent='BB,SB,UTG',
                    depth=_d25, gametype=_gt,
                    fh_start_spot='flop', fh_trainer_mode='stop_end_of_street',
                    fh_groups=RANGE_ALL),
                'Hero_4Bet': Drill(
                    name=make_drill_name('4-bet value + bluff range',
                        fh_start_spot='preflop', depth_str=_d25, gametype=_gt,
                        pot_type='3BP', pos_or_players='All'),
                    description=build_description(
                        'Facing 3-bet, 4-bet decisions with value+bluff mix',
                        '4-bet 5-12%',
                        '4-bet too low'),
                    depth=_d25, gametype=_gt,
                    fh_start_spot='preflop', fh_groups=RANGE_ALL),
                'ATS_Raw': Drill(
                    name=make_drill_name('Steal from CO/BTN first-in',
                        fh_start_spot='preflop', depth_str=_d25, gametype=_gt,
                        pot_type='-', pos_or_players='CO-BTN'),
                    description=build_description(
                        'CO/BTN first-in, open-raise steal range',
                        'ATS 32-40%',
                        'ATS too low'),
                    fh_hero='CO,BTN', depth=_d25, gametype=_gt,
                    fh_start_spot='preflop', fh_groups=RANGE_ALL),
            }
            return _recipes.get(metric_key)

        _DRILL_MAP = {}
        for _mk in ['CR_Flop_Pct', 'VPIP_PFR_Gap_Raw', 'ThreeBet_OOP',
                     'Cold_Call_NB', 'VPIP', 'AF', 'F2_Flop_CBet_Small',
                     'CBet_3BP', 'Hero_4Bet', 'ATS_Raw']:
            _dr = _make_drill(_mk)
            if _dr:
                _drill_json = _dr.to_json_line()
                _DRILL_MAP[_mk] = {
                    'name': _dr.name.split('] ')[-1] if '] ' in _dr.name else _dr.name,
                    'copy': _drill_json,
                    'reason': _dr.description.split('. ')[-1].rstrip('.') if _dr.description else '',
                }
            else:
                _DRILL_MAP[_mk] = {
                    'name': _mk.replace('_', ' '),
                    'copy': '',
                    'reason': '',
                }
        for a in red_items:
            key = a.get('metric', '')
            dm = _DRILL_MAP.get(key)
            if dm:
                drills.append(dm)
            else:
                # Generic drill from the action text
                drills.append({
                    'name': a.get('label', key),
                    'copy': f"MTT ChipEV 25bb {a.get('label', key)}",
                    'reason': a.get('action', ''),
                })
    # From aggression_drill_clusters as fallback
    if not drills:
        clusters = rd.get('aggression_drill_clusters', []) or []
        for c in clusters[:3]:
            if isinstance(c, dict) and c.get('drill'):
                drills.append({'name': c['drill'], 'copy': '', 'reason': ''})
    return drills[:3]


def _trunc_text(text, n):
    """Word-safe truncation helper."""
    if not text:
        return ''
    text = text.strip()
    # Strip markdown headers/formatting
    import re as _re_tr
    text = _re_tr.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = _re_tr.sub(r'###?\s*', '', text)
    text = _re_tr.sub(r'\n+', ' ', text)
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(' ', 1)[0]
    return cut + '…'


def _emit_opening_dashboard(doc, s, rd):
    """Opening dashboard: card-based visual summary of the session.

    Emits raw HTML into doc.lines. Called from _emit_tldr() right after
    the section heading; the old bullet-based content follows in a
    collapsible <details> block.
    """
    vol = s.get('volume', {})
    core = s.get('core', {})
    csv = s.get('csv_row', {})
    ra = rd.get('results_attribution', {})
    dt = rd.get('discipline_tier', {}) or {}
    skill = rd.get('skill_band', {}) or {}
    analyst = rd.get('analyst_commentary', {}) or {}
    hands_by_id = s.get('_hands_by_id', {}) or {}

    # v8.12.10 (pipeline trust contract): report completeness banner —
    # an auto-only render must never look like the final analyst report
    # (it did on 2026-06-13 and shipped without verdicts).
    _rc = rd.get('report_completeness') or {}
    _rc_state = _rc.get('state', '')
    # v8.12.12 Obj-D: make the coverage state obvious and quantified, and name
    # which buckets remain unreviewed. Single doc source -> MD and HTML agree.
    def _awaiting_buckets_phrase(_rcd):
        _abb = _rcd.get('awaiting_by_bucket') or {}
        if not _abb:
            return ''
        _pretty = {'punts': 'punts', 'mistakes': 'mistakes',
                   'all_in_review': 'all-in reviews', 'coolers': 'coolers',
                   'big_river_calldowns': 'river call-downs',
                   'bust_audit': 'bust audit', 'read_dependent_screening': 'read-dependent',
                   'iii4_screening': 'read-dependent', 'bestplay_screening': 'best-play screen',
                   'blindspot_sample': 'blind-spot sample'}
        parts = [f"{_n} {_pretty.get(_bk, _bk)}" for _bk, _n in
                 sorted(_abb.items(), key=lambda kv: -kv[1])]
        return ' — remaining: ' + ', '.join(parts)
    if _rc_state == 'AUTO_ONLY':
        doc.w("<div style='margin:0 0 14px;padding:12px 16px;border:2px "
              "solid #f59e0b;border-radius:12px;background:#fffbeb;"
              "color:#92400e;font-weight:700'>"
              "⚠️ AUTO-ONLY REPORT — no analyst file loaded. "
              f"{_rc.get('awaiting_candidates', '?')} candidate hands are "
              "awaiting analyst review and carry no verdicts; the verdict "
              "sections (punts / mistakes / large-loss) are INCOMPLETE. Do not "
              "treat this as the final analyst report.</div>")
        doc.w("")
    elif _rc_state == 'ANALYST_PARTIAL':
        # v8.13.1 P0: when the gap is CRITICAL coverage (loss/confirmed-error
        # hands unreviewed), surface the coverage line in amber + "not final".
        _crit_n = _rc.get('critical_unreviewed', 0)
        _cov_line = _rc.get('coverage_line', '')
        doc.w("<div style='margin:0 0 14px;padding:10px 14px;border:1px "
              "solid #bfdbfe;border-radius:12px;background:#eff6ff;"
              "color:#1e40af'>"
              f"ℹ️ Analyst coverage — PARTIAL: {_rc.get('reviewed_hands', '?')} "
              f"hand(s) reviewed of {_rc.get('candidate_need', '?')} worklist "
              f"candidate(s); {_rc.get('awaiting_candidates', '?')} still "
              "awaiting review"
              f"{_awaiting_buckets_phrase(_rc)}. Verdict sections are "
              "partially complete."
              + (f"<div style='margin-top:6px;font-weight:800;color:#b45309'>"
                 f"⚠️ {_cov_line}</div>" if _crit_n else
                 (f"<div style='margin-top:6px;font-weight:600'>{_cov_line}</div>"
                  if _cov_line else ""))
              + "</div>")
        doc.w("")
    elif _rc_state == 'ANALYST_COMPLETE':
        doc.w("<div style='margin:0 0 14px;padding:10px 14px;border:1px "
              "solid #bbf7d0;border-radius:12px;background:#f0fdf4;"
              "color:#166534'>"
              f"✅ Analyst coverage — COMPLETE: all "
              f"{_rc.get('candidate_need', '?')} worklist candidate(s) reviewed "
              f"({_rc.get('reviewed_hands', '?')} hand verdict(s) in this "
              "report)."
              + (f"<div style='margin-top:6px;font-weight:600'>"
                 f"{_rc.get('coverage_line','')}</div>"
                 if _rc.get('coverage_line') else "")
              + "</div>")
        doc.w("")
    # Game-summary absence: cash/ROI/finish fields degrade silently
    _usd_st = (rd.get('usd_overlay') or {}).get('status', '')
    if _usd_st == 'no_summaries_found':
        doc.w("<div style='margin:0 0 14px;padding:10px 14px;border:1px "
              "solid #fde68a;border-radius:12px;background:#fffbeb;"
              "color:#92400e'>"
              "⚠️ No tournament game-summary files found in this upload — "
              "cash, net, ROI, finish and flighted-advancement fields may "
              "be blank or incomplete.</div>")
        doc.w("")

    bb100 = csv.get('BB_per_100', core.get('bb_per_100', 0)) or 0
    ev_raw = core.get('ev_bb_per_100')
    true_ev = ra.get('implied_true_ev_extended_per_100', 0) if ra else (ev_raw or 0)
    total_var = ra.get('total_outcome_variance_per_100', 0) if ra else 0
    n_hands = vol.get('hands', 0)
    # Same extended fallback chain as topbar KPIs (draft.py:299)
    _usd_ov_b = rd.get('usd_overlay', {}) or {}
    n_tourneys = (vol.get('tournaments', 0)
                  or len(s.get('tournament_list', []))
                  or (_usd_ov_b.get('totals') or {}).get('n_tournaments', 0)
                  or len(s.get('_per_tourney_pnl', {})))
    n_bullets = ((_usd_ov_b.get('totals') or {}).get('n_bullets')
                 or vol.get('bullets', 0))
    avg_buyin = rd.get('avg_buyin', 0)
    total_inv = rd.get('total_invested', 0)

    # USD overlay
    _usd_ov = rd.get('usd_overlay', {}) or {}
    _hh_int = (_usd_ov.get('hh_intersect_totals')
               or _usd_ov.get('totals') or {})
    net_usd = _hh_int.get('total_net')
    roi_pct = _hh_int.get('roi_pct')

    # Punt / mistake counts — Bug fix (Ron 2026-05-30): was only counting
    # analyst III.1 verdicts, ignoring auto-detected punts. Must use the
    # same union logic as S2.1 and discipline_tier: (auto punts minus
    # analyst overrides) ∪ (analyst III.1 verdicts).
    from gem_report_draft.sections_mistakes import _PUNT_OVERRIDE_PREFIXES
    _analyst_iii1_dash = {h for h, c in analyst.items()
                         if isinstance(c, dict)
                         and (c.get('verdict', '') or '').startswith('III.1')
                         and h.startswith('TM')}
    _analyst_override_dash = {h for h, c in analyst.items()
                              if isinstance(c, dict)
                              and (c.get('verdict', '') or '').startswith(
                                  _PUNT_OVERRIDE_PREFIXES)}
    _auto_punt_ids_dash = {p.get('id') for p in (s.get('punts', {}).get('hands', []))}
    n_punts = len((_auto_punt_ids_dash - _analyst_override_dash) | _analyst_iii1_dash)
    n_mistakes = dt.get('canonical_mistakes_count',
                        dt.get('clear_mistakes_count', 0))

    # B-V10 (2026-06-01): blended invested = USD cost (settled) + filename
    # buyin (running).  _usd_tot['total_cost'] is settled-only and understates
    # when tournaments are still running.
    _usd_tot = (_usd_ov.get('hh_intersect_totals')
                or _usd_ov.get('totals') or {})
    _usd_by_tid_tl = {}
    _usd_by_name_tl = {}
    for _um in (_usd_ov.get('per_tournament') or []):
        if _um.get('tournament_id'):
            _usd_by_tid_tl[str(_um['tournament_id'])] = _um
        if _um.get('tournament'):
            _usd_by_name_tl[_um['tournament']] = _um
    _pnl_tl = s.get('_per_tourney_pnl') or rd.get('per_tourney_pnl') or []
    _disp_invested = 0
    for _pt in _pnl_tl:
        _tid = str(_pt.get('tournament_id', '') or '')
        _tn = _pt.get('tournament', '')
        _um = _usd_by_tid_tl.get(_tid) or _usd_by_name_tl.get(_tn)
        if _um and _um.get('cost'):
            _disp_invested += _um['cost']
        else:
            _disp_invested += _pt.get('buyin', 0) * _pt.get('bullets', 1)
    if not _disp_invested:
        _disp_invested = _usd_tot.get('total_cost') or total_inv
    # Ron decision (2026-06-01): Total = actual money in. If the overlay
    # knows about re-entries, its total_cost > filename total. Use the max.
    _overlay_total = _usd_tot.get('total_cost') or 0
    if _overlay_total > _disp_invested:
        _disp_invested = _overlay_total

    he = _html_escape

    # ---- Compute dashboard data ----
    status_emoji, status_text, status_cls = _dashboard_status(
        bb100, true_ev, n_punts, total_var)
    headline = _dashboard_headline(bb100, true_ev, total_var)
    subtitle = _dashboard_subtitle(bb100, true_ev, total_var,
                                    n_punts, n_mistakes, dt)
    believe, dont_overreact = _dashboard_beliefs(
        bb100, true_ev, total_var, n_punts, ra)
    var_rows = _dashboard_variance_rows(ra)
    fix_items = _dashboard_fix_items(s, rd, analyst)
    hand_queue = _dashboard_hands_to_open(s, rd, analyst, hands_by_id)
    n_coolers, n_big_unclass, cooler_ids = _dashboard_cooler_summary(
        s, rd, analyst)
    watch_items = _dashboard_watchlist_items(s, rd)
    drill_items = _dashboard_drill_items(s, rd)

    # Disc label for scorecard
    disc_label = dt.get('label', '—') if dt else '—'
    disc_emoji = dt.get('emoji', '⚪') if dt else '⚪'

    # ---- Emit HTML ----
    doc.w('<div class="opening-dashboard">')

    # === Row 1: Hero + Scorecard ===
    doc.w('<div class="od-row">')

    # Hero card
    doc.w('<div class="opening-hero">')
    doc.w(f'<span class="od-eyebrow od-eyebrow-{he(status_cls)}">'
          f'{status_emoji} {he(status_text)}</span>')
    doc.w(f'<div class="od-headline">{he(headline)}</div>')
    doc.w(f'<p class="od-lead">{he(subtitle)}</p>')
    # v8.4.2: Decision dashboard — What happened / What matters / What to do next
    doc.w('<div class="od-decision-grid">')
    # What happened
    _what_happened = (f'You played {n_hands} hands across {n_tourneys} tournaments. '
                      f'True EV was {("strongly positive" if true_ev > 5 else "positive" if true_ev > 0 else "negative")} '
                      f'at {true_ev:+.1f} bb/100, actual result was {bb100:+.1f} bb/100. '
                      f'{"Variance took back part of the edge." if total_var < -3 else "Variance added to the edge." if total_var > 3 else "Variance was roughly neutral."}')
    doc.w('<div class="od-dec-card">')
    doc.w('<span class="od-label">What happened</span>')
    doc.w(f'<span class="od-text">{he(_what_happened)}</span>')
    doc.w('</div>')
    # What matters
    _what_matters_parts = [believe]
    if n_punts == 0 and n_mistakes <= 2:
        _what_matters_parts.append('Process was clean — focus on volume, not fixes.')
    elif n_mistakes > 3:
        _what_matters_parts.append(f'{n_mistakes} mistakes flagged — review before next session.')
    _ie_issues = rd.get('issue_explorer_issues', [])
    _n_with_hands = sum(1 for i in _ie_issues if i.get('all_hand_ids'))
    if _n_with_hands:
        _what_matters_parts.append(f'{_n_with_hands} issues have reviewable hand evidence.')
    doc.w('<div class="od-dec-card">')
    doc.w('<span class="od-label">What matters</span>')
    doc.w(f'<span class="od-text">{he(" ".join(_what_matters_parts))}</span>')
    doc.w('</div>')
    # What to do next (compact)
    _next_parts = []
    if _n_with_hands:
        _next_parts.append('Review Candidate issues with available evidence first.')
    # v8.12.4 (QA item 2): the dashboard, S5.1 Promoted Leaks and the S6.0
    # watchlist each named a different "#1". The PROMOTED list is the
    # canonical next-session focus — quote it here verbatim; fix_items only
    # serves as fallback when nothing was promoted.
    _promo_a2 = (rd.get('leak_persistence', {}) or {}).get('current_leaks', []) or []
    _promo_names_a2 = [(_p if isinstance(_p, str)
                        else (_p.get('name') or _p.get('leak') or ''))
                       for _p in _promo_a2]
    _promo_names_a2 = [p for p in _promo_names_a2 if p][:3]
    if _promo_names_a2:
        _next_parts.append('Drill the promoted leaks (S5.1): '
                           + ' + '.join(_promo_names_a2) + '.')
    elif fix_items:
        _fix_title = (fix_items[0].get('title') or fix_items[0].get('name') or '').strip()[:40]
        if _fix_title:
            _next_parts.append(f'Drill the top confirmed leak: {_fix_title}.')
        else:
            _next_parts.append('Drill watchlist items — no confirmed leak this session.')
    if dont_overreact:
        _next_parts.append(dont_overreact)
    doc.w('<div class="od-dec-card">')
    doc.w('<span class="od-label">What to do next</span>')
    for _np in _next_parts[:3]:
        doc.w(f'<span class="od-text">• {he(_np)}</span>')
    doc.w('</div>')
    doc.w('</div>')  # od-decision-grid
    doc.w('</div>')  # opening-hero

    # Scorecard
    def _sc_row(label, val_str, cls='', tip=''):
        cls_attr = f' {cls}' if cls else ''
        tip_attr = f' data-tip="{he(tip)}"' if tip else ''
        return (f'<div class="od-score-row"{tip_attr}>'
                f'<span class="od-score-label">{he(label)}</span>'
                f'<span class="od-score-val{cls_attr}">{val_str}</span>'
                f'</div>')

    bb_cls = 'od-green' if bb100 > 0 else ('od-red' if bb100 < 0 else '')
    ev_cls = 'od-green' if true_ev > 0 else ('od-red' if true_ev < 0 else '')
    var_cls = 'od-red' if total_var < -1 else ('od-green' if total_var > 1 else '')

    doc.w('<div class="session-scorecard">')
    doc.w('<div class="od-card-title">Session scorecard</div>')
    doc.w('<div class="od-score">')
    doc.w(_sc_row('Actual result', f'{bb100:+.1f}', bb_cls))
    # v8.12.8 (handover Issue 2): a degraded equity engine (phevaluator
    # missing / per-hand fallbacks) makes the all-in-luck layer — and so
    # True EV — approximate. Mark it instead of presenting it as exact.
    _ev_degraded = rd.get('eai_equity_degraded')
    doc.w(_sc_row('True EV',
                  f'{true_ev:+.1f}' + (' ⚪' if _ev_degraded else ''), ev_cls,
                   tip=('APPROXIMATE — equity engine degraded '
                        f"({rd.get('eai_equity_method') or 'heuristic'}): "
                        'EAI buckets used a rank heuristic for some or all '
                        'all-ins. Install phevaluator and re-run for exact '
                        'True EV. '
                        if _ev_degraded else '')
                       + 'Full four-layer variance-adjusted EV. '
                       'True EV adjusts for all 4 variance layers (all-in luck, card quality, made hands, coolers).'))
    if total_var:
        doc.w(_sc_row('Variance impact', f'{total_var:+.1f}', var_cls))
    doc.w(_sc_row('Discipline', f'{disc_emoji} {he(disc_label)}', ''))
    # Confidence (skill band CI if available)
    _ci = skill.get('ci_width')
    if _ci:
        doc.w(_sc_row('Confidence', f'{_ci}%', ''))
    doc.w('</div>')  # od-score
    # Score note
    _synth = (analyst.get('__synthesis__', {}) or {})
    _si = _synth.get('session_interpretation') if isinstance(_synth, dict) else None
    score_note = ''
    if isinstance(_si, dict) and _si.get('read'):
        # Use first sentence of the analyst read
        _read = _si['read']
        _first = _read.split('. ')[0].strip().rstrip('.') + '.'
        if len(_first) > 120:
            _first = _first[:120].rsplit(' ', 1)[0] + '…'
        score_note = _first
    if not score_note:
        score_note = he(status_text)
    doc.w(f'<p class="od-score-note">{he(score_note)}</p>')
    doc.w('</div>')  # session-scorecard

    doc.w('</div>')  # od-row

    # === Metric strip ===
    def _metric(label, val, cls=''):
        cls_attr = f' {cls}' if cls else ''
        return (f'<div class="od-metric{cls_attr}">'
                f'<span class="od-metric-label">{he(label)}</span>'
                f'<span class="od-metric-val">{val}</span></div>')

    doc.w('<div class="opening-metric-grid">')
    doc.w(_metric('Hands', f'{n_hands:,}'))
    doc.w(_metric('Tourneys', str(n_tourneys)))
    doc.w(_metric('Bullets', str(n_bullets)))
    _abi_fmt = (f'${avg_buyin:.2f}'[:-3] if avg_buyin and f'{avg_buyin:.2f}'.endswith('.00')
                else f'${avg_buyin:.2f}') if avg_buyin else '—'
    doc.w(_metric('ABI', _abi_fmt))
    _inv_fmt = (f'${_disp_invested:,.2f}'[:-3] if _disp_invested and f'{_disp_invested:.2f}'.endswith('.00')
                else f'${_disp_invested:,.2f}') if _disp_invested else '—'
    doc.w(_metric('Invested', _inv_fmt))
    # Punts/mistakes — green when zero
    pm_cls = ' od-metric-good' if (n_punts == 0 and n_mistakes == 0) else (
        ' od-metric-bad' if n_punts >= 3 else '')
    doc.w(_metric('Punts / mistakes', f'{n_punts} / {n_mistakes}', pm_cls))
    doc.w('</div>')  # metric-grid

    # P2 #15: Top 3 issues from Issue Explorer (visible without scrolling)
    _ie_issues = rd.get('issue_explorer_issues', [])
    _top3 = [i for i in _ie_issues if i.get('tier') in ('confirmed', 'candidate', 'shadow')][:3]
    if _top3:
        doc.w('<div class="od-top3">')
        doc.w('<b style="font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Top issues</b>')
        for _ti in _top3:
            _tier_cls = 'od-badge-red' if _ti.get('tier') == 'confirmed' else 'od-badge-amber'
            doc.w(f'<div class="od-top3-item">'
                  f'<span class="od-badge {_tier_cls}">{_ti.get("tier","?").title()}</span> '
                  f'{he(_ti.get("name",""))}</div>')
        doc.w('</div>')

    # === Row 2: Variance card + What to fix ===
    if var_rows or fix_items:
        doc.w('<div class="od-row">')

        # Variance card
        if var_rows:
            total_v_str = f'{total_var:+.1f}'
            v_badge_cls = 'od-badge-amber' if total_var < 0 else 'od-badge-green'
            doc.w('<div class="od-card variance-story-card">')
            doc.w('<div class="od-card-header">')
            doc.w('<div class="od-card-title">Why the result '
                  f'{"looked smaller than the play" if total_var < 0 else "ran ahead"}'
                  '</div>')
            doc.w(f'<span class="od-badge {v_badge_cls}">'
                  f'Variance {total_v_str} bb/100</span>')
            doc.w('</div>')  # header
            doc.w('<div class="od-vrows">')
            for _, emoji, label, detail, val, cls, _anchor in var_rows:
                doc.w(f'<div class="variance-row {cls}">')
                doc.w(f'<span class="od-vr-emoji">{emoji}</span>')
                doc.w(f'<div><span class="od-vr-title">{he(label)}</span>'
                      f'<span class="od-vr-detail">{he(detail)}</span></div>')
                doc.w(f'<span class="od-vr-num">{val:+.1f}</span>')
                doc.w('</div>')
            doc.w('</div>')  # od-vrows
            doc.w('</div>')  # variance-story-card
        else:
            doc.w('<div class="od-card variance-story-card">')
            doc.w('<div class="od-card-header">')
            doc.w('<div class="od-card-title">Variance impact</div>')
            doc.w('<span class="od-badge od-badge-green">Neutral</span>')
            doc.w('</div>')
            doc.w('<p class="od-card-desc">'
                  'All variance layers within ±0.5 bb/100 of neutral — '
                  'no major luck swing.</p>')
            doc.w('</div>')

        # What to fix card
        if fix_items:
            doc.w('<div class="od-card next-fix-card">')
            doc.w('<div class="od-card-header">')
            doc.w('<div class="od-card-title">What to fix next session</div>')
            doc.w('<span class="od-badge od-badge-blue">Measured leaks</span>')
            doc.w('</div>')
            doc.w('<div class="od-fix-list">')
            for i, item in enumerate(fix_items, 1):
                color_cls = {'blue': ' od-fix-blue',
                             'purple': ' od-fix-purple'}.get(item['color'], '')
                doc.w(f'<div class="od-fix-item{color_cls}">')
                doc.w(f'<div class="od-fix-rank">{i}</div>')
                doc.w('<div>')
                # Fix: if hand IDs available, make title a hand-list popup
                # so user sees the actual hands, not a section they can't parse
                _fix_hids = item.get('hand_ids', [])
                if _fix_hids:
                    _fh_str = ','.join(_fix_hids)
                    _fh_name = he(item['name'])
                    _fh_title = f'{_fh_name} ({len(_fix_hids)} hands)'
                    doc.w(f'<div class="od-fix-title">'
                          f'<a class="hand-list-trigger" href="#" '
                          f'data-hids="{_fh_str}" '
                          f'data-list-title="{_fh_title}">'
                          f'{_fh_name}</a></div>')
                elif item.get('section_link'):
                    doc.w(f'<div class="od-fix-title">'
                          f'<a href="#{item["section_link"]}">{he(item["name"])}</a></div>')
                else:
                    doc.w(f'<div class="od-fix-title">{he(item["name"])}</div>')
                if item.get('detail'):
                    doc.w(f'<p class="od-fix-desc">{he(_trunc_text(item["detail"], 160))}</p>')
                if item.get('bb100') is not None:
                    doc.w(f'<div class="od-fix-rule">'
                          f'Estimated impact: {item["bb100"]:+.2f} BB/100</div>')
                doc.w('</div>')
                doc.w('</div>')
            doc.w('</div>')  # fix-list
            doc.w('</div>')  # next-fix-card
        else:
            doc.w('<div class="od-card next-fix-card">')
            doc.w('<div class="od-card-header">')
            doc.w('<div class="od-card-title">What to fix next session</div>')
            doc.w('<span class="od-badge od-badge-green">Clean</span>')
            doc.w('</div>')
            doc.w('<p class="od-card-desc">'
                  'No measured leaks above threshold this session.</p>')
            doc.w('</div>')

        doc.w('</div>')  # od-row

    # === Row 3: Coach watchlist + Drill script ===
    if watch_items or drill_items:
        doc.w('<div class="od-row">')

        # Coach watchlist
        doc.w('<div class="od-card coach-watchlist-card">')
        doc.w('<div class="od-card-header">')
        doc.w('<div class="od-card-title">Coach watchlist</div>')
        doc.w('<span class="od-badge od-badge-purple">Training focus</span>')
        doc.w('</div>')
        doc.w('<p class="od-card-desc">'
              'Separate from scored leaks — areas to watch during next session.</p>')
        if watch_items:
            doc.w('<div class="od-watch-grid">')
            for w in watch_items:
                _ws = w.get('section', '')
                doc.w('<div class="od-watch-item">')
                if _ws:
                    doc.w(f'<a href="#{_ws}" class="od-watch-name" '
                          f'style="text-decoration:none;color:inherit">'
                          f'{he(w["name"])}</a>')
                else:
                    doc.w(f'<span class="od-watch-name">{he(w["name"])}</span>')
                if w.get('desc'):
                    doc.w(f'<span class="od-watch-desc">{he(w["desc"])}</span>')
                doc.w('</div>')
            doc.w('</div>')  # watch-grid
        else:
            doc.w('<p class="od-card-desc">⚪ No specific watch items this session.</p>')
        # Amit coaching flags (session-specific rule violations)
        _cflags = s.get('coaching_flags', [])
        if _cflags:
            _cflag_rules = {}
            for cf in _cflags:
                _cflag_rules.setdefault(cf['rule'], []).append(cf)
            doc.w('<div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--line)">')
            doc.w(f'<span style="font-size:11px;font-weight:800;color:var(--warn)">'
                  f'COACHING FLAGS ({len(_cflags)})</span>')
            for _rule, _items in _cflag_rules.items():
                _label = {
                    'MW_SMALL_SIZING': 'MW pot: sizing too small with value',
                    'OOP_CHECK_CALL_SHOULD_BET': 'OOP check-call: consider betting',
                    'CHEAP_TOURNEY_SMALL_SIZING': 'Cheap tourney: size up value bets',
                    'BVB_DEEP_RAGGED_OPEN': 'BvB deep: don\'t open bottom range',
                }.get(_rule, _rule.replace('_', ' '))
                _ids = [it['id'] for it in _items if it.get('id')][:10]
                if _ids:
                    _hstr = ','.join(_ids)
                    doc.w(f'<div style="font-size:12px;margin:4px 0">'
                          f'<a class="hand-list-trigger" href="#" '
                          f'data-hids="{_hstr}" '
                          f'data-list-title="{_label} ({len(_items)})">'
                          f'{_label} ({len(_items)})</a></div>')
                else:
                    doc.w(f'<div style="font-size:12px;margin:4px 0">'
                          f'{_label} ({len(_items)})</div>')
            doc.w('</div>')
        # C-bet → barrel correlation stat
        _cbc = s.get('coaching_cbet_barrel_correlation', {})
        if _cbc.get('big_cbet', 0) >= 5 or _cbc.get('small_cbet', 0) >= 5:
            _big_rate = (100 * _cbc['big_barrel'] / _cbc['big_cbet']
                         if _cbc['big_cbet'] else 0)
            _small_rate = (100 * _cbc['small_barrel'] / _cbc['small_cbet']
                           if _cbc['small_cbet'] else 0)
            doc.w(f'<div style="font-size:11px;color:var(--muted);margin-top:6px">'
                  f'C-bet→barrel: big sizing {_big_rate:.0f}% barrel rate '
                  f'(n={_cbc["big_cbet"]}), small {_small_rate:.0f}% '
                  f'(n={_cbc["small_cbet"]})</div>')
        doc.w('</div>')  # coach-watchlist-card

        # Drill script
        doc.w('<div class="od-card">')
        doc.w('<div class="od-card-header">')
        doc.w('<div class="od-card-title">Pre-session drill script</div>')
        doc.w('<span class="od-badge od-badge-green">Use before playing</span>')
        doc.w('</div>')
        if drill_items:
            doc.w('<div class="od-drill-list">')
            for i, d in enumerate(drill_items, 1):
                if isinstance(d, dict):
                    _dn = d.get('name', '—')
                    _dc = d.get('copy', '')
                    _dr = d.get('reason', '')
                    if _dc:
                        # Clickable name → copies GTOW search string to clipboard
                        doc.w(f'<div class="od-drill">'
                              f'<a href="#" class="od-drill-copy" '
                              f'data-copy="{he(_dc)}" '
                              f'onclick="navigator.clipboard.writeText(this.dataset.copy)'
                              f'.then(function(){{if(window._toast)window._toast(\'Copied GTOW drill to clipboard\');}})'
                              f';return false;" '
                              f'title="Click to copy GTOW search string">'
                              f'<strong>{i}.</strong> {he(_dn)}</a>'
                              f'{(" — <em>" + he(_dr) + "</em>") if _dr else ""}'
                              f'</div>')
                    else:
                        doc.w(f'<div class="od-drill"><p class="od-drill-text">'
                              f'<strong>{i}.</strong> {he(_dn)}'
                              f'{(" — <em>" + he(_dr) + "</em>") if _dr else ""}'
                              f'</p></div>')
                else:
                    doc.w(f'<div class="od-drill"><p class="od-drill-text">{he(str(d))}</p></div>')
            doc.w('</div>')
        else:
            doc.w('<p class="od-card-desc">'
                  '⚪ No drill script configured for this session.</p>')
        doc.w('</div>')  # drill card

        doc.w('</div>')  # od-row

    # === Row 4: Hands to open + Coolers ===
    if hand_queue or n_coolers or n_big_unclass:
        doc.w('<div class="od-row">')

        # v8.14.0 Slice C: compact prioritized Hand Review Queue (upgrades the
        # old "Hands to open first" list — same block, not a new section). Rows
        # are full-row clickable and open the EXISTING V25 modal in queue
        # context; open/reviewed partition, counts, top-N, and the celebratory
        # cleared state are managed by the PBReviewQueue JS controller reading
        # the canonical review store.
        # v8.14.1 rev-3 (Blocker 7): when EVERY queued hand is an auto-clear (no
        # punts / analyst mistakes / leak examples), this is not an urgent "open
        # first" queue — it is an optional auto-cleared sample. Reframe the
        # title/sub/count so it never reads as N urgent hands that in fact all
        # say "no analyst action needed". The count is JS-managed (PBReviewQueue),
        # so we also flag the card with data-all-auto-clear for the controller.
        _all_auto = bool(hand_queue) and all(
            h.get('bucket') == 'auto_clear' for h in hand_queue)
        _rq_title = ('Auto-cleared sample · optional review' if _all_auto
                     else 'Hands to open first')
        _rq_sub = ('Quick-scan sample — nothing here needs analyst action'
                   if _all_auto
                   else 'Review queue · highest priority hands first')
        # v8.14.1 P0-7: "Your review:" + "marked by you" so the user-local review
        # state never reads as the analyst's coverage status (the JS counter in
        # _html.py mirrors this exact wording on load).
        _rq_count0 = (f'Your review: {len(hand_queue)} auto-cleared · 0 marked by you'
                      if _all_auto
                      else f'Your review: {len(hand_queue)} open · 0 marked by you')
        doc.w('<div class="od-card rq-card" id="review-queue" '
              f'data-queue-ids="{he(",".join(h["id"][-8:] for h in hand_queue))}" '
              + ('data-all-auto-clear="1" ' if _all_auto else '')
              + 'data-topn="6">')
        doc.w('<div class="rq-head">'
              f'<div><div class="rq-title">{he(_rq_title)}</div>'
              f'<div class="rq-sub">{he(_rq_sub)}</div></div>'
              f'<span class="rq-count" id="rq-count">{he(_rq_count0)}</span>'
              '</div>')
        if hand_queue:
            _bc = {}
            for h in hand_queue:
                _bc[h['bucket']] = _bc.get(h['bucket'], 0) + 1
            _strip = ['<span class="rq-priority-label">Priority</span>']
            for _bk in _REVIEW_QUEUE_BUCKETS:
                if _bc.get(_bk):
                    _strip.append(f'<span class="rq-bcount">'
                                  f'{he(_REVIEW_QUEUE_BUCKET_LABEL[_bk])} {_bc[_bk]}</span>')
            doc.w('<div class="rq-priority" title="Priority: punts -> analyst mistakes '
                  '-> known-leak examples -> auto clear -> marginal.">'
                  + ' '.join(_strip) + '</div>')
            doc.w('<div class="rq-list" id="rq-list">')
            for h in hand_queue:
                short_id = h['id'][-8:]
                _h = hands_by_id.get(h['id'])
                _cards = h.get('cards', '') or (''.join((_h or {}).get('cards', [])))
                _pills = _cards_str_to_pills(_cards) if _cards else ''
                _net = round(h.get('net', 0) or 0, 1)
                _bbcls = 'pos' if _net > 0 else ('neg' if _net < 0 else 'neu')
                _bbtxt = f"{'+' if _net > 0 else ''}{_net:.1f} BB"
                # degrade gracefully: only show a BB pill when the hand has data
                _bb = (f'<span class="bb-pill {_bbcls}">{_bbtxt}</span>'
                       if _h is not None else '')
                doc.w(f'<div class="rq-row" role="button" tabindex="0" '
                      f'data-hand-id="{he(short_id)}" data-bucket="{he(h["bucket"])}">'
                      f'<span class="rq-rank">{h["rank"]}</span>'
                      f'<span class="rq-hid">{he(short_id)}</span>'
                      f'<span class="handcards">{_pills}</span>'
                      f'<span class="reason reason-{he(h["bucket"])}">{he(h["reason_label"])}</span>'
                      f'<span class="rq-main"><span class="rq-row-title">'
                      f'{he(h.get("title", ""))}</span></span>'
                      f'{_bb}'
                      f'<span class="rq-status" data-hand-id="{he(short_id)}"></span>'
                      '</div>')
            doc.w('</div>')  # rq-list
            # v8.14.1 rev-2 (#1): the reviewed/completed list is collapsed by
            # default (rq-reviewed-list `hidden`, head aria-expanded=false); the
            # caret makes the expand affordance discoverable. Open/needs-review
            # hands stay visible in the rq-list above; only the COMPLETED list
            # collapses, so unresolved bugs/debates are never hidden.
            doc.w('<div class="rq-reviewed" id="rq-reviewed" hidden>'
                  '<button type="button" class="rq-reviewed-head" id="rq-reviewed-head" '
                  'aria-expanded="false">'
                  '<span class="rq-rev-caret" id="rq-rev-caret" aria-hidden="true">▸</span> '
                  '<span class="rq-rev-label">Reviewed (0) / follow-ups (0)</span> '
                  '<span class="rq-revchips" id="rq-revchips"></span></button>'
                  '<div class="rq-reviewed-list" id="rq-reviewed-list" hidden></div>'
                  '</div>')
            doc.w('<div class="rq-empty-win" id="rq-empty-win" hidden>'
                  '<div class="rq-trophy">🏆</div>'
                  '<div class="rq-win-title">Priority queue cleared — nice work.</div>'
                  '<div class="rq-win-sub">Review streak complete · +1 session discipline</div>'
                  '</div>')
            doc.w('<div class="rq-footer"><span class="rq-foot-note" id="rq-foot-note"></span>'
                  '<button type="button" class="rq-showall" id="rq-showall" hidden>Show all</button>'
                  '</div>')
        else:
            doc.w('<p class="od-card-desc">'
                  '⚪ No priority hands flagged this session.</p>')
        doc.w('</div>')  # rq-card

        # Coolers / large losses
        doc.w('<div class="od-card cooler-summary-card">')
        doc.w('<div class="od-card-header">')
        doc.w('<div class="od-card-title">Coolers / large losses</div>')
        doc.w('<span class="od-badge od-badge-blue">Explainers, not drills</span>')
        doc.w('</div>')
        doc.w('<div class="od-vrows">')
        if n_coolers:
            _ck_hids = ','.join(c[-8:] for c in cooler_ids[:20])
            _ck_pills = ' · '.join(
                f'<a href="#sec-app-hand-{c[-8:]}" class="hand-ref" '
                f'data-hand-id="{c[-8:]}">{c[-8:]}</a>'
                for c in cooler_ids[:4])
            extra = f' (+{n_coolers - 4} more)' if n_coolers > 4 else ''
            doc.w(f'<div class="variance-row">')
            doc.w(f'<span class="od-vr-emoji">\U0001f7e6</span>')
            doc.w(f'<div><span class="od-vr-title">'
                  f'<a class="hand-list-trigger" href="#" '
                  f'data-hids="{_ck_hids}" '
                  f'data-list-title="Coolers ({n_coolers})">'
                  f'{n_coolers} justified cooler{"s" if n_coolers != 1 else ""}'
                  f'</a></span>'
                  f'<span class="od-vr-detail">{_ck_pills}{he(extra)}</span></div>')
            doc.w(f'<span class="od-vr-num">Review optional</span>')
            doc.w('</div>')
        if n_big_unclass:
            doc.w(f'<div class="variance-row">')
            doc.w(f'<span class="od-vr-emoji">✅</span>')
            doc.w(f'<div><span class="od-vr-title">'
                  f'{n_big_unclass} other big-loss hand{"s" if n_big_unclass != 1 else ""}'
                  f'</span>'
                  f'<span class="od-vr-detail">&gt;25BB lost, not classified as leaks'
                  f'</span></div>')
            doc.w(f'<span class="od-vr-num">Not urgent</span>')
            doc.w('</div>')
        if not n_coolers and not n_big_unclass:
            doc.w('<p class="od-card-desc">'
                  '\U0001f7e2 No coolers or unclassified large losses.</p>')
        doc.w('</div>')  # vrows
        doc.w('<div class="od-fix-rule">'
              'Review coolers only after the actionable queue, '
              'or when you need emotional closure.</div>')
        doc.w('</div>')  # cooler card

        doc.w('</div>')  # od-row

    doc.w('</div>')  # opening-dashboard
    doc.w('')


def _emit_tldr(doc, s, rd):
    # Phase 4.8: TLDR is now a proper segment with doc.section() — gets its own
    # chapter card, nav entry, and review row like every other section.
    vol = s.get('volume', {})
    core = s.get('core', {})
    csv = s.get('csv_row', {})
    avg_buyin = rd.get('avg_buyin', 0)
    total_inv = rd.get('total_invested', 0)
    # n_tourneys/n_bullets needed by legacy summary block below
    _usd_tldr = rd.get('usd_overlay', {}) or {}
    n_tourneys = (vol.get('tournaments', 0)
                  or len(s.get('tournament_list', []))
                  or (_usd_tldr.get('totals') or {}).get('n_tournaments', 0)
                  or len(s.get('_per_tourney_pnl', {})))
    n_bullets = ((_usd_tldr.get('totals') or {}).get('n_bullets')
                 or vol.get('bullets', 0))
    bb100 = csv.get('BB_per_100', core.get('bb_per_100', 0))
    ev_bb100 = csv.get('EV_BB_per_100', core.get('ev_bb_per_100', '—'))
    skill = rd.get('skill_band', {})
    hcl = rd.get('hero_classification', {})
    cq = s.get('card_quality', {})
    prem = cq.get('premiums_pct', 0)
    ra = rd.get('results_attribution', {})
    _tldr_summary = f"{skill.get('emoji','⚪')} {skill.get('label','—')} — {bb100:+.2f} bb/100"
    doc.section("sec-0", "Summary", _tldr_summary)

    # Phase 4.8: Opening Dashboard — card-based visual summary
    _emit_opening_dashboard(doc, s, rd)

    # Wrap old bullet-based content in a collapsible for reference
    doc.w('<details><summary><strong>📋 Detailed summary (legacy format)</strong>'
          ' — click to expand</summary>')
    doc.w('')

    # ============================================================
    # B69 (v7.49, Ron 2026-05-12): COMPACT TL;DR
    # ============================================================
    # Headline now reads in 6-12 lines instead of a 50-line wall. Structure:
    #   1. Volume + result one-liners (2 lines)
    #   2. Variance impact (3-5 bullets from attribution components)
    #   3. Top hands today (2-4 bullets — punts + III.4 reads + coolers + "rest justified")
    #   4. Top leaks for next session (2-4 bullets, ONLY confirmed-not-variance)
    #   5. Skill/discipline summary (1-2 lines)
    #   6. Walk-Backs collapsible with emoji severity column
    # The big Result Attribution table moves into <details> — link to I.4
    # for the full breakdown.
    # ============================================================

    # --- Line 1-2: Volume + Result ---
    # B-V10 (2026-06-01): blended invested (same as the stat-card and P&L
    # total). Recompute rather than reuse the dashboard's _disp_invested
    # (different scope — this function may be called independently).
    _usd_ov_es = rd.get('usd_overlay', {}) or {}
    _usd_tot = (_usd_ov_es.get('hh_intersect_totals')
                or _usd_ov_es.get('totals') or {})
    _usd_by_tid_es = {}
    _usd_by_name_es = {}
    for _um in (_usd_ov_es.get('per_tournament') or []):
        if _um.get('tournament_id'):
            _usd_by_tid_es[str(_um['tournament_id'])] = _um
        if _um.get('tournament'):
            _usd_by_name_es[_um['tournament']] = _um
    _pnl_es = s.get('_per_tourney_pnl') or rd.get('per_tourney_pnl') or []
    _disp_invested = 0
    for _pt in _pnl_es:
        _tid = str(_pt.get('tournament_id', '') or '')
        _tn = _pt.get('tournament', '')
        _um = _usd_by_tid_es.get(_tid) or _usd_by_name_es.get(_tn)
        if _um and _um.get('cost'):
            _disp_invested += _um['cost']
        else:
            _disp_invested += _pt.get('buyin', 0) * _pt.get('bullets', 1)
    if not _disp_invested:
        _disp_invested = _usd_tot.get('total_cost') or total_inv
    _overlay_total_es = _usd_tot.get('total_cost') or 0
    if _overlay_total_es > _disp_invested:
        _disp_invested = _overlay_total_es
    doc.w(f"- **{vol.get('hands',0)} hands** / {n_tourneys} tourneys / "
          f"{n_bullets} bullets — avg buy-in **${avg_buyin}** "
          f"({_fmt_usd(_disp_invested)} total invested) {_xref('sec-1-1', label='↗')}")
    if ra:
        implied_ev = ra.get('implied_true_ev_extended_per_100', 0)
        doc.w(f"- **Result:** {bb100:+.2f} bb/100 surface | "
              f"**True EV (var-adjusted): {implied_ev:+.2f} bb/100** "
              f"{_xref('sec-1-4', label='full breakdown ↗')}")
    else:
        doc.w(f"- **Result:** {bb100:+.2f} bb/100 actual | EV: {ev_bb100} bb/100 "
              f"{_xref('sec-6-2', label='↗')}")
    # B47 (v7.52, Ron 2026-05-18): USD overlay — buyin-weighted reality check.
    # BB/100 weights every hand equally; USD reality is dominated by buyin
    # concentration in expensive bustouts. Surface both so the gap is visible.
    usd_ov = rd.get('usd_overlay', {}) or {}
    hh_int = usd_ov.get('hh_intersect_totals')
    if hh_int and hh_int.get('n_tournaments', 0) > 0:
        net = hh_int['total_net']
        roi = hh_int['roi_pct']
        emoji = '🟢' if net > 0 else ('🟡' if net > -200 else '🔴')
        cost = hh_int['total_cost']
        # Concentration warning when top-3 cost > 50% of total
        top3_share = hh_int.get('top3_cost_share', 0)
        concentration_note = ''
        if top3_share > 0.5:
            concentration_note = (f" ⚠️ top-3 cost {top3_share*100:.0f}% concentrated; "
                                  f"biggest loss **{_fmt_usd(hh_int['biggest_loss_usd'], plus=True)}** "
                                  f"({hh_int['biggest_loss_tournament'][:35]})")
        doc.w(f"- **USD reality:** {emoji} **{_fmt_usd(net, plus=True)}** net "
              f"({roi:+.1f}% ROI on {_fmt_usd(cost)} invested across "
              f"{hh_int['n_tournaments']} tourneys, {hh_int['n_bullets']} bullets) "
              f"{_xref('sec-1-1a', label='by-day P&L ↗')}"
              + concentration_note)
        # v8.12.5 (QA item 8): name what is NOT settled — flighted bags and
        # tournaments with no summary file — so "winning/losing session" is
        # read against the right denominator.
        _adv_t = usd_ov.get('advanced_tournaments') or []
        _unres_t = usd_ov.get('unresolved_hh_tournaments') or []
        if _adv_t or _unres_t:
            _bits_unres = []
            if _adv_t:
                _bits_unres.append(
                    f"**{len(_adv_t)} flighted advancement"
                    f"{'s' if len(_adv_t) != 1 else ''}** (bagged chips, no "
                    f"cash yet: {', '.join(n[:30] for n in _adv_t[:2])})")
            if _unres_t:
                _bits_unres.append(
                    f"**{len(_unres_t)} tournament"
                    f"{'s' if len(_unres_t) != 1 else ''} without a game "
                    f"summary** ({', '.join(n[:30] for n in _unres_t[:2])})")
            doc.w(f"- ⏳ **Unsettled:** {' · '.join(_bits_unres)} — these are "
                  f"outside the USD net above.")
    doc.w("")

    # B209 (Ron review 2026-05-25): human interpretation of the session. Ron
    # can read the metrics himself — what the TL;DR was missing is a genuine
    # READ: how the session went and what the Result Attribution breakdown
    # actually means for him. Analyst-written slot (not metric-derived
    # boilerplate), stored in __synthesis__.session_interpretation.
    _synth_si = (rd.get('analyst_commentary', {}) or {}).get('__synthesis__', {})
    _si = _synth_si.get('session_interpretation') if isinstance(_synth_si, dict) else None
    if isinstance(_si, dict) and _si.get('read'):
        doc.w("**🧭 The read:**")
        doc.w("")
        doc.w(_si['read'])
        doc.w("")
        # B211 (Ron review 2026-05-25): the attribution_guide used to render
        # here too — two essays stacked in the headline. It now renders inside
        # the Result Attribution collapsible (where the data it explains is).

    # --- Variance impact bullets (from attribution data) ---
    if ra:
        # B110 (Ron 2026-05-19): include actual total in the header so
        # "📊 Variance impact today (-7.2 bb/100):" replaces the bare label.
        _total_var = ra.get('total_outcome_variance_per_100', 0)
        _tv_emoji = '🥶' if _total_var < 0 else ('🔥' if _total_var > 0 else '')
        doc.w(f"**📊 Variance impact today ({_tv_emoji} {_total_var:+.1f} bb/100):**")
        # Build sorted list of components by absolute magnitude
        components = []
        eai_per100 = ra.get('eai_variance_per_100', 0)
        if abs(eai_per100) >= 0.5:
            sign = '🥶' if eai_per100 < 0 else '🔥'
            components.append((abs(eai_per100), sign, 'All-in luck',
                              eai_per100, ra.get('eai_variance_bb', 0),
                              'sec-i-4'))
        mh = ra.get('made_hands_var_per_100', 0)
        if abs(mh) >= 0.5:
            sign = '🥶' if mh < 0 else '🔥'
            mh_dir = 'boards bricked' if mh < 0 else 'boards cooperated'
            components.append((abs(mh), sign, f'Made hands ({mh_dir})',
                              mh, ra.get('made_hands_var_bb', 0),
                              'sec-i-6'))
        cq_per100 = ra.get('card_quality_var_per_100', 0)
        if abs(cq_per100) >= 0.5:
            sign = '🔥' if cq_per100 > 0 else '🥶'
            cq_dir = 'ran hot on cards' if cq_per100 > 0 else 'ran cold on cards'
            components.append((abs(cq_per100), sign, f'Card quality ({cq_dir})',
                              cq_per100, ra.get('card_quality_var_bb', 0),
                              'sec-i-5'))
        cooler_per100 = ra.get('cooler_var_per_100', 0)
        if abs(cooler_per100) >= 0.5:
            sign = '🔥' if cooler_per100 > 0 else '🥶'
            cooler_dir = ('cooled less than expected' if cooler_per100 > 0
                          else 'coolered more than expected')
            components.append((abs(cooler_per100), sign, f'Cooler freq ({cooler_dir})',
                              cooler_per100, ra.get('cooler_var_bb', 0),
                              'sec-i-7'))
        # Sort descending by magnitude
        components.sort(key=lambda x: -x[0])
        for _, sign, label, per100, bb_total, _anchor in components[:4]:
            _det = f" {_xref(_anchor, label='details \u2197')}" if _anchor else ""
            doc.w(f"- {sign} **{label}:** {per100:+.2f}/100 ({bb_total:+.1f} BB){_det}")
        if not components:
            doc.w("- 🟢 All variance layers within ±0.5 bb/100 of neutral — no major luck swing")
        # B46 (v7.51, Ron 2026-05-18): Deep-loss concentration. Articulates the
        # "felt brutal" perception — variance that hits at deep stacks hurts
        # disproportionately. Surface when there are ≥3 large losses at
        # ≥50BB eff AND those account for >50% of negative variance impact.
        n_deep_l = ra.get('n_deep_losses', 0)
        deep_share = ra.get('deep_loss_share', 0)
        deep_loss_bb = ra.get('deep_loss_bb', 0)
        worst_deep = ra.get('worst_deep_loss_hands', []) or []
        if n_deep_l >= 3 and deep_share > 0.4:
            concentration = ra.get('deep_concentration', 'moderate')
            emoji = '🔴' if concentration == 'high' else '🟡'
            max_loss = ra.get('max_single_deep_loss_bb', 0)
            top_3_ids = [w['id'][-8:] for w in worst_deep[:3] if w.get('id')]
            id_str = (' (' + ', '.join(f'`{x}`' for x in top_3_ids) + ')'
                      if top_3_ids else '')
            doc.w(f"- {emoji} **Deep-stack loss concentration ({concentration}):** "
                  f"{n_deep_l} large losses at ≥50BB eff totaling {deep_loss_bb:+.0f} BB "
                  f"({deep_share*100:.0f}% of negative variance). Worst single: "
                  f"{max_loss:+.0f} BB{id_str}")
        doc.w("")

    # --- Top hands today — from analyst commentary ---
    analyst = (rd.get('analyst_commentary') or {})
    iii0_hands = [(hid, cmt) for hid, cmt in analyst.items()
                  if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.0')
                  and hid.startswith('TM')]
    iii1_hands = [(hid, cmt) for hid, cmt in analyst.items()
                  if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.1')
                  and hid.startswith('TM')]
    iii4_hands = [(hid, cmt) for hid, cmt in analyst.items()
                  if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.4')
                  and hid.startswith('TM')]
    iii3_hands = [(hid, cmt) for hid, cmt in analyst.items()
                  if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.3')
                  and hid.startswith('TM')]
    # B142 (Ron 2026-05-23): III.2 Mistake — analyst-confirmed strategic mistake
    # (non-punt). Closes the taxonomy gap where the analyst could only clear
    # (III.0/III.3/4/5), confirm a punt (III.1) or cooler (I.7) — with no way to AFFIRM
    # a non-punt mistake. A III.2 verdict is a leak, not a cleared hand.
    iii2_hands = [(hid, cmt) for hid, cmt in analyst.items()
                  if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.2')
                  and hid.startswith('TM')]
    coolers_list = list((rd.get('coolers') or s.get('coolers', {}).get('hands', []) or []))
    i7_analyst = [(hid, cmt) for hid, cmt in analyst.items()
                  if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('I.7')
                  and hid.startswith('TM')]

    # B158 (Ron 2026-05-23): B144 structural guarantee. The "Top leaks" table
    # below itemizes MDA missed-exploit hands; the same hand must not also
    # surface in "Top hands today". Pre-compute the MDA-missed ID set here
    # (same analyst-rejection gate as the Top-leaks builder uses) so the
    # Top-hands block can exclude them. Belt-and-suspenders alongside the
    # analyst `mda_review: rejected` per-hand gate.
    _mda_rejected_pre = {hid for hid, c in analyst.items()
                         if isinstance(c, dict) and c.get('mda_review') == 'rejected'}
    topleak_ids = {(m.get('hand_id') or '')
                   for m in ((s.get('mda_exploits', {}) or {}).get('missed', []) or [])
                   if isinstance(m, dict)
                   and (m.get('hand_id') or '') not in _mda_rejected_pre}
    topleak_ids.discard('')
    # Bug D fix: also exclude analyst-verdicted leak hands (III.1/III.2/III.4)
    # from cooler_refs so they don't appear in BOTH Top hands AND Top leaks
    _analyst_leak_ids = {hid for hid, c in analyst.items()
                         if isinstance(c, dict)
                         and (c.get('verdict', '') or '').startswith(('III.1', 'III.2', 'III.4'))}
    topleak_ids |= _analyst_leak_ids

    hands_by_id_full = s.get('_hands_by_id', {}) or {}

    def _net(hid):
        h = hands_by_id_full.get(hid)
        if h: return h.get('net_bb', 0)
        # Fallback to appendix_hand_details
        ah = (rd.get('appendix_hand_details') or {}).get(hid, {})
        return ah.get('net_bb', 0) if isinstance(ah, dict) else 0

    # Helper: word-safe truncate
    def _trunc(text, n):
        if not text: return ''
        text = text.strip()
        if len(text) <= n: return text
        cut = text[:n].rsplit(' ', 1)[0]
        return cut + '…'
    iii5_hands = [(hid, cmt) for hid, cmt in analyst.items()
                  if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.5')
                  and hid.startswith('TM')]
    # B255: EAI lookup for auto-inferring lost_flip on III.5 hands
    _eai_lookup = {}
    for _e in (s.get('eai', {}).get('hands', []) or []):
        _eai_lookup[_e.get('id', '')] = _e
    # B210 (Ron 2026-05-25): verdict-code labels decoupled from section
    # numbers. The III.x verdict codes are a stable internal taxonomy; after
    # the section renumber they no longer line up 1:1 with section numbers, so
    # the display label drops the number and uses the descriptive word.
    _vmap = {
        'III.0': ('⚖️', 'GTO-Standard'),
        'III.1': ('👎', 'punt'),
        'III.2': ('👎', 'strategic leak'),
        'III.4': ('📖', 'read-dependent'),
        'III.3': ('👍', 'cleared'),
        'III.5': ('👍', 'justified'),
    }
    # B144 (Ron 2026-05-23): de-duplicate the TL;DR. III.1 punts and III.4
    # read-dep hands are ALWAYS itemized in the "Top leaks" table below
    # (Confirmed-punts row / Read-dependent-calls row). Listing them here too
    # presented the SAME hand twice in one screen — once as a "Top hand", once
    # as a leak. "Top hands today" now carries only reviewed hands that are NOT
    # leak-table entries: III.0 GTO-Standard, III.3 cleared, III.5 justified, and coolers — the
    # "reviewed, not a leak" reel. Punts and reads appear exactly once, in Top
    # leaks. iii1_hands/iii4_hands are still folded into already_classified_ids
    # below so a punt/read is never miscounted as an unclassified big loss.
    # B116 ordering (|net_bb| desc) is retained for the hands that remain.
    unified = []
    for hid, cmt in (iii0_hands + iii3_hands + iii5_hands):
        if hid in topleak_ids:
            continue  # B158: itemized in Top leaks — don't double-present
        vcls = (cmt.get('verdict', '') or '').split()[0]
        emoji, label = _vmap.get(vcls, ('•', vcls or '—'))
        # B149: III.3/III.5 hands with an `outcome` show sub-label
        # (🤢 Suckout / 🪙 Lost flip / 🪤 vs Top of range) instead of generic.
        # B255: also auto-infer lost_flip from EAI equity for III.5 preflop
        # all-ins with 42-58% equity — "lost flip" not just "justified".
        if vcls == 'III.3':
            _oce, _oct = _outcome_label(cmt, default=(emoji, 'cleared'))
            emoji, label = _oce, _oct
        elif vcls == 'III.5':
            _oce, _oct = _outcome_label(cmt, default=(emoji, 'justified'))
            emoji, label = _oce, _oct
            # Auto-infer lost_flip if no explicit outcome but EAI shows flip
            if label == 'justified':
                _eai_e = _eai_lookup.get(hid)
                if (_eai_e
                        and not _eai_e.get('won', True)
                        and 0.42 <= (_eai_e.get('hero_equity', 0) or 0) <= 0.58):
                    emoji, label = '🪙', 'lost flip'
        # Item 1: III.0 GTO-Standard also supports outcome sub-labels.
        elif vcls == 'III.0':
            _oce, _oct = _outcome_label(cmt, default=(emoji, 'GTO-Standard'))
            emoji, label = _oce, _oct
        unified.append((hid, cmt, emoji, label))
    unified.sort(key=lambda t: -abs(_net(t[0])))
    # Coolers — dedupe across auto-detected and analyst-tagged I.7
    cooler_ids_seen = set()
    cooler_refs = []
    for c in coolers_list:
        cid = c.get('id') if isinstance(c, dict) else None
        if cid and cid not in cooler_ids_seen and cid not in topleak_ids:
            cooler_ids_seen.add(cid)
            cooler_refs.append(f"[`{cid[-8:]}`](#sec-app-hand-{cid[-8:]})")
    for hid, _ in i7_analyst:
        if hid not in cooler_ids_seen and hid not in topleak_ids:
            cooler_ids_seen.add(hid)
            cooler_refs.append(f"[`{hid[-8:]}`](#sec-app-hand-{hid[-8:]})")
    cooler_total = len(cooler_ids_seen)
    # Big losses NOT classified anywhere → justified-variance bucket. III.1/III.4
    # stay in already_classified_ids (they're classified — just shown in Top
    # leaks), so they are correctly excluded from this "unclassified" bucket.
    already_classified_ids = (
        {hid for hid, _ in iii0_hands+iii1_hands+iii2_hands+iii4_hands+iii3_hands+iii5_hands+i7_analyst}
        | cooler_ids_seen | topleak_ids
    )
    big_busts = [h for h in hands_by_id_full.values()
                 if h.get('net_bb', 0) < -25
                 and h.get('id') not in already_classified_ids]
    n_justified = len(big_busts)
    # Emit the block only when there is a non-leak hand to show — otherwise the
    # 🎯 header would render with nothing under it (punts/reads alone no longer
    # populate this section).
    if unified or cooler_total or n_justified:
        doc.w("**🎯 Top hands today** — *reviewed hands that aren't leaks; "
              "punts and reads appear in Top leaks below*")
        for hid, cmt, emoji, label in unified[:6]:
            net = _net(hid)
            spot = _trunc(cmt.get('spot', ''), 90)
            # B183 (Ron review 2026-05-25): analyst entries carry only
            # verdict+argument (no `spot` field), so the bullet rendered
            # "**label:** — net" with an empty blurb. Fall back to the
            # argument's TL;DR first sentence so every row says something.
            if not spot:
                _arg = cmt.get('argument', '') or ''
                if '**TL;DR:**' in _arg:
                    _tl = _arg.split('**TL;DR:**', 1)[1].lstrip()
                    _tl = _tl.split('\n', 1)[0].strip()
                    _tl = _tl.split('. ', 1)[0].rstrip('.')
                    spot = _trunc(_tl, 120)
            net_str = f" — {net:+.1f}BB" if net else ""
            doc.w(f"- {emoji} [`{hid[-8:]}`](#sec-app-hand-{hid[-8:]}) **{label}:** "
                  f"{spot}{net_str}")
        if cooler_total:
            refs_str = ', '.join(cooler_refs[:3])
            extra = f" (+{cooler_total - 3} more)" if cooler_total > 3 else ''
            doc.w(f"- 🟦 **{cooler_total} cooler{'s' if cooler_total != 1 else ''}** "
                  f"(justified): {refs_str}{extra}")
        if n_justified:
            doc.w(f"- ✅ Other **{n_justified} big-loss hand{'s' if n_justified != 1 else ''}** "
                  f"(>25BB lost): not classified as leaks "
                  f"{_xref('sec-1-3', label='see S1.3 ↗')}")
        doc.w("")

    # --- Top leaks for next session (skill-attributable, NOT variance) ---
    # Sources: (a) leak_persistence.current_leaks (b) afb below-target slices
    # (c) aggression_drill_clusters
    afb = rd.get('af_breakdown', {}) or {}
    drill_clusters = rd.get('aggression_drill_clusters', []) or []
    persistence_leaks = (rd.get('leak_persistence', {}) or {}).get('current_leaks', []) or []
    persistence_summary = (rd.get('leak_persistence', {}) or {}).get('summary', {}) or {}
    next_session_items = []

    # Helper: extract the most useful "leak detail" sentence from analyst prose.
    # Prefer sentences that name the structural issue over those that just
    # describe the action sequence.
    def _extract_leak_sentence(argument, fallback_spot):
        if not argument:
            return (fallback_spot or '')[:140]
        sentences = [s.strip() for s in argument.replace('\n', ' ').split('. ') if s.strip()]
        if not sentences:
            return (fallback_spot or argument or '')[:140]
        STRUCTURAL_KEYWORDS = (
            'structur', 'blocker', 'sizing', 'leak', 'fold-freq', 'population',
            'frequency', 'calibration', 'overbet', 'donk', 'punt', 'misclass',
            'reclassif', 'check 4 was', 'failed check', 'better line',
            'should have', 'cleaner line', 'cleaner option', 'risk', 'exploit',
        )
        ACTION_KEYWORDS = ('action:', 'co opens', 'utg opens', 'btn opens',
                           'mp opens', 'hj opens', 'sb opens', 'hero opens',
                           'preflop:', 'opens to', 'raises to', 'calls', 'bets')
        def score(s):
            ls = s.lower()
            score = 0
            for kw in STRUCTURAL_KEYWORDS:
                if kw in ls:
                    score += 3
            for kw in ACTION_KEYWORDS:
                if ls.startswith(kw) or kw in ls[:20]:
                    score -= 2
            return score
        scored = [(score(s), i, s) for i, s in enumerate(sentences)]
        scored.sort(key=lambda t: (-t[0], t[1]))
        best = scored[0][2] if scored else sentences[0]
        if len(best) > 140:
            best = best[:140].rsplit(' ', 1)[0] + '…'
        return best

    # B76 (v7.50, Ron 2026-05-12): describe the LEAK PATTERN, not the
    # individual hand. Aggregate III.1 + III.4 hands by category and surface
    # count + total BB + key structural concept. Hands are still linked but
    # the bullet talks about the pattern.
    def _detect_pattern_label(cmts):
        """Heuristically derive a pattern label from analyst commentary spots."""
        if not cmts: return None
        # Collect spot text from all entries
        spots = ' '.join(c.get('spot', '').lower() for _, c in cmts)
        args = ' '.join((c.get('argument', '') or '').lower() for _, c in cmts)
        text = spots + ' ' + args
        if 'river overbet' in text or ('river' in text and 'overbet' in text):
            return 'River overbet structure'
        if 'donk' in text and 'river' in text:
            return 'River donk-lead structure'
        if 'triple-barrel' in text or 'triple barrel' in text:
            return 'Triple-barrel polarized line'
        if 'turn jam' in text or 'turn shove' in text:
            return 'Turn jam with combo-draw equity'
        if 'cbet' in text and 'sizing' in text:
            return 'CBet sizing on dynamic boards'
        return None

    def _common_structural_thread(cmts, _extract):
        """Find the structural issue mentioned across all entries."""
        threads = []
        for _, c in cmts:
            arg = c.get('argument', '') or c.get('matchup_math', '')
            if arg:
                threads.append(_extract(arg, c.get('spot', '')))
        if not threads: return None
        # Look for common keywords
        joined = ' '.join(threads).lower()
        themes = []
        if 'blocker' in joined or 'no diamond' in joined or 'no club' in joined:
            themes.append('blocker selection')
        if 'sizing' in joined or 'overbet' in joined:
            themes.append('sizing for OOP polarized lines')
        if 'population' in joined or 'fold-freq' in joined or 'calibration' in joined:
            themes.append('pool fold-frequency calibration')
        if 'structural' in joined or 'structurally' in joined:
            themes.append('structural commit decisions')
        if themes:
            return ', '.join(themes)
        # Fallback to the first thread truncated
        return threads[0][:120] if threads else None

    # B76 (v7.50, Ron 2026-05-12): GROUP hands by ACTUAL sub-pattern, not by
    # verdict only. Earlier draft averaged 4 heterogeneous III.4 hands under
    # one "river overbet" label even though only 1 was actually that pattern.
    # Now: detect each hand's individual pattern, then emit one bullet per
    # pattern group within the verdict tier.
    def _hand_subpattern(cmt):
        # B117 (Ron 2026-05-20): prefer the analyst-set `pattern` field over
        # regex-guessing from prose. The keyword heuristic mis-tagged hands —
        # e.g. a river call-down and a one-pair turn-jam both matched
        # 'turn jam (combo-draw)' because their argument prose happened to
        # mention 'turn' and 'jam'. When the analyst tags `pattern` explicitly
        # it is used verbatim as the cluster key (and as the display label via
        # the _PAT_LABELS.get(pat, pat) fallback). Keyword heuristic remains
        # only for un-tagged legacy entries.
        explicit = (cmt.get('pattern') or '').strip()
        if explicit:
            return explicit
        spot = (cmt.get('spot', '') or '').lower()
        arg = (cmt.get('argument', '') or '').lower()
        text = spot + ' ' + arg
        if 'river overbet' in text or ('overbet' in text and 'river' in text):
            return 'river overbet'
        if 'donk-overbet' in text or ('donk' in text and 'river' in text):
            return 'river donk-overbet'
        if 'triple-barrel' in text or 'triple barrel' in text:
            return 'triple-barrel'
        if 'turn jam' in text or 'turn shove' in text or ('jam' in text and 'turn' in text):
            return 'turn jam (combo-draw)'
        if 'flop x/r' in text or ('check-raise' in text and 'flop' in text):
            return 'flop x/r AI'
        if '4-bet' in text or ('3-bet' in text and 'preflop' in text):
            return 'preflop commit (3b/4b depth)'
        if 'preflop' in text and ('walk-back' in text or 'walkback' in text):
            return 'preflop walk-back'
        return 'other'

    def _group_by_pattern(hands_list):
        """Return {pattern: [(hid, cmt), ...]}"""
        from collections import defaultdict
        groups = defaultdict(list)
        for hid, cmt in hands_list:
            groups[_hand_subpattern(cmt)].append((hid, cmt))
        return groups

    # Tier 1: III.1 punts — ONE aggregate bullet with inline pattern breakdown
    # B109 (Ron 2026-05-19): pattern label casing dict — .title() broke
    # "Flop x/r AI" into "Flop X/R Ai". Hand-rolled per pattern for readability.
    _PAT_LABELS = {
        'river overbet':                  'River overbet',
        'river donk-overbet':             'River donk-overbet',
        'triple-barrel':                  'Triple-barrel',
        'turn jam (combo-draw)':          'Turn jam (combo-draw)',
        'flop x/r AI':                    'Flop x/r AI',
        'flop x/r ai':                    'Flop x/r AI',
        'preflop commit (3b/4b depth)':   'Preflop 3b/4b commit',
        'preflop walk-back':              'Preflop walk-back',
        'other':                          'Other',
    }
    # B112 (Ron 2026-05-19): Top Leaks uses BB/100 not BB total, with per-
    # subtype hand examples inline. Session total hands is the BB/100 denom.
    _total_session_hands = s.get('volume', {}).get('hands', 0) or len(hands) or 1
    def _bb_per_100(bb):
        return (bb / _total_session_hands) * 100 if _total_session_hands else 0
    if iii1_hands:
        groups = _group_by_pattern(iii1_hands)
        total_bb = sum(_net(hid) for hid, _ in iii1_hands)
        total_n = len(iii1_hands)
        # Build bullet list — one per pattern, with examples inline.
        pattern_bullets = []
        for pat, group in sorted(groups.items(),
                                  key=lambda kv: -sum(abs(_net(h)) for h, _ in kv[1])):
            if pat == 'other':
                continue
            grp_bb = sum(_net(hid) for hid, _ in group)
            grp_bb_100 = _bb_per_100(grp_bb)
            refs = ' '.join(f"[`{hid[-8:]}`](#sec-app-hand-{hid[-8:]})"
                            for hid, _ in group[:3])
            pat_disp = _PAT_LABELS.get(pat, pat)
            pattern_bullets.append(
                f"• **{pat_disp}** × {len(group)} ({grp_bb_100:+.2f} BB/100) — {refs}")
        dominant_pat = max((p for p in groups.keys() if p != 'other'),
                           key=lambda p: sum(abs(_net(h)) for h, _ in groups[p]),
                           default='other')
        label = (f"Punts — {dominant_pat}" if dominant_pat != 'other'
                 else "Confirmed punts")
        total_bb_100 = _bb_per_100(total_bb)
        detail = (f"**{total_n} confirmed punt{'s' if total_n != 1 else ''}** "
                  f"({total_bb_100:+.2f} BB/100)<br>" + '<br>'.join(pattern_bullets))
        # B116 (Ron 2026-05-19): ev slot now holds signed BB/100 (for table
        # column display + sort-by-impact). Was previously abs(BB-total).
        next_session_items.append(('🔴', label, detail, None, total_bb_100))

    # Tier 1: III.4 read-deps — captured as a WATCH item, NOT a confirmed leak.
    # B131 (Ron 2026-05-20, revised): read-dependent (III.4) calls are NOT
    # excluded from Top Leaks and are NOT rolled into a loss-selected aggregate
    # BB/100 — both were assumptions not backed by data. Instead every III.4
    # call is surfaced individually with the specific read it hinges on (the
    # analyst key_decision): "gone over" per hand. A III.4 call is a leak only
    # where the read it needs is unsupported; where the read is sound it is
    # fine. The reader sees each call and its read, not a verdict-by-exclusion.
    iii4_watch = None
    if iii4_hands:
        iii4_entries = []
        for hid, cmt in iii4_hands:
            read = (cmt.get('key_decision') or cmt.get('pattern') or '').strip()
            pat = cmt.get('pattern', '') or ''
            iii4_entries.append({
                'hid': hid, 'read': read,
                'pattern': _PAT_LABELS.get(pat, pat),
                'net': _net(hid),
            })
        iii4_watch = {'entries': iii4_entries, 'n': len(iii4_entries)}

    # B131c (Ron 2026-05-20): read-dependent calls are a real leak BUCKET and
    # belong IN the Top Leaks table.
    # v7.60 (Ron 2026-05-20): the bucket is now QUANTIFIED. The river
    # call/fold solver prices each call's chip-EV vs FOLD at the population
    # baseline (rd['read_dependent_quant']); the bucket impact is the sum,
    # in BB/100. This is the EV of the DECISION, not the hand's net result —
    # a read-dependent call inside a big bust still only risks the river bet.
    # Turn (or earlier) bluff-catches are not river-solvable and are counted
    # separately rather than folded into the number.
    if iii4_watch and iii4_watch['entries']:
        _rd_quant = rd.get('read_dependent_quant', {}) or {}
        _rd_lines = []
        _leak_bb = 0.0       # sum of EV given up on pop-FOLD calls (a cost)
        _n_solv = 0          # river-solvable calls
        _n_leak = 0          # of those, calls that are -EV vs the pool
        _n_unsolved = 0      # turn/earlier — not river-solvable
        def _short_read(txt):
            """First clause of a key_decision/pattern, capped — III.4 has full."""
            t = (txt or '').strip()
            for sep in (' — ', ' – ', '; ', ': '):
                if sep in t:
                    t = t.split(sep)[0].strip()
                    break
            t = t.rstrip('.')
            return (t[:54].rstrip() + '…') if len(t) > 55 else t

        for _e in sorted(iii4_watch['entries'], key=lambda x: x['net']):
            _ref = (f"[`{_e['hid'][-8:]}`]"
                    f"(#sec-app-hand-{_e['hid'][-8:]})")
            _label = _short_read(_e['pattern'] or _e['read'])
            _q = _rd_quant.get(_e['hid'])
            if _q and _q.get('solvable'):
                _n_solv += 1
                _vp = _q.get('verdict_pop', 'CALL')
                _pev = _q.get('ev_call_pop_bb', 0.0)
                if _vp == 'FOLD':
                    _leak_bb += _pev
                    _n_leak += 1
                    _qtag = f"**FOLD {_pev:+.1f} BB**"
                elif _vp == 'INDIFF':
                    _qtag = "~indifferent"
                else:
                    _qtag = "holds vs pool ✓"
            else:
                _n_unsolved += 1
                _qtag = "*not priced*"
            _rd_lines.append(f"• {_ref} · {_label} · {_qtag}")
        _q_bb100 = _bb_per_100(_leak_bb) if _n_leak else 0.0
        if _n_solv:
            _hdr = (f"**{iii4_watch['n']} read-dependent calls** — bucket "
                    f"leak **{_q_bb100:+.2f} BB/100** ({_leak_bb:+.1f} BB): "
                    f"{_n_leak}/{_n_solv} river-solvable -EV vs the pool"
                    + (f", {_n_unsolved} turn/earlier not priced"
                       if _n_unsolved else "")
                    + ". Per-hand analysis in the read-dependent section.<br>")
        else:
            _hdr = (f"**{iii4_watch['n']} read-dependent calls** — all "
                    f"turn/earlier, not river-solvable, so unpriced this "
                    f"session. Per-hand analysis in the read-dependent section.<br>")
        next_session_items.append(('👁', 'Read-dependent calls',
            _hdr + '<br>'.join(_rd_lines),
            'sec-iii-4', _q_bb100))

    # Tier 2: AF cross-slice leaks with biggest gaps
    if drill_clusters:
        top_cluster = drill_clusters[0]
        slice_key = top_cluster.get('slice_key', '?')
        gap = top_cluster.get('slice_gap', 0)
        n = top_cluster.get('spot_count', 0)
        if gap >= 0.8:
            next_session_items.append(('🟡', f"AF leak: `{slice_key}`",
                                       f"{gap:+.2f} below target band, {n} missed-aggression "
                                       f"spot{'s' if n != 1 else ''} this session",
                                       'sec-iv-5', None))

    # Sizing-precision lane (Ron 2026-05-20): geometric c-bet compliance +
    # IP 3-bet sizing deviation rate. A NAMED lane in Top Leaks so sizing
    # errors don't silently fall through. No fabricated BB/100 — sizing
    # misexecution has no clean per-hand net — so impact renders "—" and the
    # row sorts last rather than dominating on a guessed number.
    _sc = s.get('sizing_consistency', {}) or {}
    _i3 = s.get('ip_3bet_sizing', {}) or {}
    _geo = _sc.get('geometric_pct')
    _dev = _i3.get('deviation_rate_pct')
    _siz_bits = []
    if _geo is not None and _geo < 70:
        _siz_bits.append(f"geometric c-bet compliance {_geo:.0f}% (target ≥70%, "
                         f"{_sc.get('erratic', 0)} erratic hand(s))")
    if _dev is not None and _dev > 15:
        _siz_bits.append(f"IP 3-bet sizing {_dev:.0f}% off-target "
                         f"({_i3.get('deviation_count', 0)}/{_i3.get('total_count', 0)} "
                         f"hands vs J44 bands)")
    if _siz_bits:
        _siz_emoji = ('🔴' if ((_geo is not None and _geo < 60)
                               or (_dev is not None and _dev > 30)) else '🟡')
        next_session_items.append((_siz_emoji, 'Sizing precision',
                                   ' · '.join(_siz_bits), 'sec-viii', None))

    # B78 (v7.50, Ron 2026-05-12): MDA missed-exploit population-level leaks.
    # These are PARALLEL to III.x — Hero's action deviated from the MDA
    # population recommendation. EV deltas are smaller per-event than III.1/4
    # but they're skill-attributable misses worth surfacing in the headline
    # so the TL;DR captures all leak axes, not just analyst-flagged hands.
    # B106 (Ron 2026-05-19): group by RECOMMENDED ACTION (jam/rejam/3bet/
    # etc.) instead of MDA-N code. Ron wants short clear text in headline,
    # not codes. The recommended action is the actionable signal — "should
    # have jammed 41 times" is what matters, not the MDA classifier ID.
    mda_missed = (s.get('mda_exploits', {}) or {}).get('missed', []) or []
    # B133 (Ron 2026-05-20): the MDA missed-exploit list is analyst-gated. An
    # MDA recommendation is a population-frequency signal, not a range-validated
    # play — it can recommend a jam in a spot the immediate range makes -EV
    # (folding out worse, isolating into dominators; cold-jamming into a tight
    # 3-bettor; ignoring satellite ICM). When the analyst reviews the hand and
    # rejects the recommendation (mda_review == 'rejected'), that hand is NOT a
    # missed exploit. Only analyst-confirmed or unreviewed MDA hands count.
    _mda_rejected = {hid for hid, c in analyst.items()
                     if isinstance(c, dict) and c.get('mda_review') == 'rejected'}
    _mda_all_n = len(mda_missed)
    mda_missed = [m for m in mda_missed
                  if isinstance(m, dict)
                  and (m.get('hand_id') or '') not in _mda_rejected]
    _mda_rejected_n = _mda_all_n - len(mda_missed)
    if mda_missed:
        from collections import defaultdict
        action_groups = defaultdict(list)
        for m in mda_missed:
            if not isinstance(m, dict): continue
            hero_act = (m.get('hero_action') or 'mixed').lower()
            mda_act = (m.get('mda_action') or 'mixed').lower()
            key = f"{hero_act}→{mda_act}"
            action_groups[key].append(m)
        total_ev = sum((m.get('ev_bb') or 0) for m in mda_missed)
        n_total = len(mda_missed)
        action_bullets = []
        for action_key, items in sorted(action_groups.items(),
                                        key=lambda kv: -sum((m.get('ev_bb') or 0) for m in kv[1])):
            ev = sum((m.get('ev_bb') or 0) for m in items)
            ev_per_100 = _bb_per_100(ev)
            refs = ' '.join(f"[`{(m.get('hand_id') or '')[-8:]}`]"
                            f"(#sec-app-hand-{(m.get('hand_id') or '')[-8:]})"
                            for m in items[:3])
            # B125 (Ron 2026-05-20): MDA hands are linked here as raw markdown,
            # bypassing _hand_ref()'s citation tracking. Register them so they
            # are NOT dropped from XIV.B as "uncited" — otherwise these links
            # are dead. Register every MDA hand, not just the 3 shown inline,
            # since the appendix entry must exist for all of them.
            for _m in items:
                _hid = _m.get('hand_id') if isinstance(_m, dict) else None
                if _hid:
                    _state._record_citation_explicit(_hid, 'sec-top-leaks',
                                              'MDA exploits missed — next-session focus')
            label = action_key[0].upper() + action_key[1:] if action_key else 'Mixed'
            action_bullets.append(
                f"• **{label}** × {len(items)} ({ev_per_100:+.2f} BB/100) — {refs}")
        total_ev_100 = _bb_per_100(total_ev)
        _rej_note = (f" — {_mda_rejected_n} other MDA flag"
                     f"{'s' if _mda_rejected_n != 1 else ''} rejected on analyst "
                     f"review (recommendation wrong for the spot)"
                     if _mda_rejected_n else "")
        next_session_items.append(('🟡', 'MDA population exploits missed',
                                    f"**{n_total} hand{'s' if n_total != 1 else ''}** "
                                    f"({total_ev_100:+.2f} BB/100 est) — Hero's action "
                                    f"diverged from MDA recommendation{_rej_note}<br>"
                                    + '<br>'.join(action_bullets),
                                    'sec-xiii-5-2', total_ev_100))

    # Tier 3: persistence-tracked leaks (recurring across sessions)
    for leak in persistence_leaks[:2]:
        if not isinstance(leak, dict): continue
        name = leak.get('name', leak.get('leak', '—'))
        ev_cost = leak.get('ev_cost_per_100', 0) or leak.get('ev_per_100', 0)
        sessions = leak.get('sessions_seen', 0) or leak.get('persistence', 0)
        next_session_items.append(('🟡', f"Recurring: {name}",
                                    f"{ev_cost:+.2f} BB/100 EV cost over {sessions} session(s)",
                                    'sec-ix', None))

    # B77 (v7.50, Ron 2026-05-12): positive note when prior leaks RESOLVED
    # and no new leaks recurring. Surfaces the win when the work paid off.
    n_recurring = persistence_summary.get('recurring', 0)
    n_resolved = persistence_summary.get('resolved', 0)
    if n_recurring == 0 and n_resolved > 0 and not persistence_leaks:
        next_session_items.append(('🟢', "Persistence streak",
                                    f"None of last session's flagged leaks recurred — "
                                    f"{n_resolved} resolved {_xref('sec-12', label='see S12 ↗')}",
                                    None, None))

    if next_session_items:
        # B105 (Ron 2026-05-19): Top Leaks reformatted as a structured TABLE.
        # Previous bullet form was unscanable. New columns: Type / Details /
        # Hand Examples. Merging rules:
        #   - III.1 → single "Confirmed punts" row (no "III.1" prefix per Ron)
        #   - III.4 → single "Read-dependent calls" row
        #   - MDA   → single "MDA exploits missed" row; MDA-N codes replaced
        #             with human-readable action descriptions (e.g. "raise→jam")
        #   - III.2 synthesis leaks (Caller IP Agg, SB BvB, Triple Barrel
        #             Over-Calling, Draw Overbet Jams, IP Stab Rate) join the
        #             same table so the headline captures METRIC leaks not
        #             only verdict-aggregated ones.
        doc.w("<<ANCHOR:sec-top-leaks>>")
        doc.w("**📌 Top leaks — notice for next session:**")
        # v8.13.1 P0: when CRITICAL coverage is incomplete the leak list is
        # built from an incomplete review — it must not imply final analyst
        # confidence. Downgrade with an explicit provisional caveat.
        _rc_tl = rd.get('report_completeness') or {}
        if not _rc_tl.get('critical_coverage_ok', True):
            doc.w(f"> ⚠️ **Provisional — coaching confidence reduced.** "
                  f"{_rc_tl.get('critical_unreviewed', 0)} critical hand(s) "
                  f"unreviewed; these leaks are not the final analyst read.")
        doc.w("")

        # Pull III.2 confirmed metric leaks from __synthesis__
        _synth_top = (rd.get('analyst_commentary', {}) or {}).get('__synthesis__', {})
        _leaks_meta = _synth_top.get('leaks', {}) if isinstance(_synth_top, dict) else {}
        _metric_rows = []
        for leak_name, leak_meta in _leaks_meta.items():
            if not isinstance(leak_meta, dict):
                continue
            verdict_raw = (leak_meta.get('real_or_noise') or '').lower()
            if 'real' in verdict_raw:
                emoji = '🔴'
            elif 'mixed' in verdict_raw:
                emoji = '🟡'
            else:
                # Skip noise/pending — only surface confirmed leaks here
                continue
            metric = leak_meta.get('metric_summary') or '—'
            bb100 = leak_meta.get('bb_per_100_est')  # B116: pull for table column
            exs = leak_meta.get('examples', []) or []
            ex_refs = []
            for ex in exs[:3]:
                if isinstance(ex, dict):
                    hid = ex.get('hand_id', '')
                else:
                    hid = ex
                if hid:
                    ex_refs.append(f"[`{hid[-8:]}`](#sec-app-hand-{hid[-8:]})")
            ex_str = ' '.join(ex_refs) if ex_refs else '*(cross-session pattern, no specific hand examples)*'
            _metric_rows.append((emoji, leak_name, metric, ex_str, bb100))

        # B114: hand examples are inline per-subtype in details; no separate column.
        import re as _re_tl
        # v7.60: each Top-Leaks type links to its own section. Canonical
        # types map to a fixed anchor; non-canonical rows keep the anchor
        # passed through from next_session_items.
        _TYPE_ANCHORS = {
            'Confirmed punts': 'sec-iii-1',
            'Read-dependent calls': 'sec-iii-4',
            'MDA exploits missed': 'sec-xiii-5',
        }
        def _table_row_from_item(emoji, title, detail, bb100, src_anchor=None):
            # B108: normalize to canonical type names.
            tl = title.lower()
            if 'punt' in tl or 'iii.1' in tl:
                type_clean = 'Confirmed punts'
            elif 'read' in tl or 'iii.4' in tl:
                type_clean = 'Read-dependent calls'
            elif 'mda' in tl:
                type_clean = 'MDA exploits missed'
            elif 'af leak' in tl or 'aggression' in tl:
                type_clean = title
            elif 'recurring' in tl:
                type_clean = title.replace('Recurring: ', '')
            else:
                type_clean = title
            anchor = _TYPE_ANCHORS.get(type_clean, src_anchor)
            return (emoji, type_clean, detail, bb100, anchor)

        # B116: sort by abs(BB/100) DESC — biggest impact first regardless of sign.
        verdict_rows = [_table_row_from_item(it[0], it[1], it[2], it[4],
                                             it[3] if len(it) > 3 else None)
                        for it in next_session_items[:6]]
        # Metric rows: append inline hand examples to details
        metric_rows_inline = []
        for emoji, name, metric, ex_str, bb100 in _metric_rows:
            details_with_examples = f"{metric}<br>{ex_str}"
            # III.2 synthesis metric leaks link to the Strategic Leaks section.
            metric_rows_inline.append((emoji, name, details_with_examples,
                                       bb100, 'sec-iii-2'))

        # Combine + sort by impact magnitude DESC
        all_rows = verdict_rows + metric_rows_inline
        all_rows.sort(key=lambda r: -abs(r[3] or 0))

        # B117 (Ron 2026-05-19): Pareto filter — show leaks in the top 95%
        # of cumulative |BB/100| impact, with min 5 rows. Plus header gets
        # the signed total so Ron can see overall leak magnitude.
        _signed_total = sum((r[3] or 0) for r in all_rows)
        _abs_total = sum(abs(r[3] or 0) for r in all_rows)
        cumulative = 0.0
        pareto_cutoff_idx = 0
        for i, r in enumerate(all_rows):
            cumulative += abs(r[3] or 0)
            if _abs_total > 0 and cumulative / _abs_total >= 0.95:
                pareto_cutoff_idx = i + 1
                break
        else:
            pareto_cutoff_idx = len(all_rows)
        n_show = max(pareto_cutoff_idx, 5)
        n_show = min(n_show, len(all_rows))
        n_dropped = len(all_rows) - n_show
        all_rows = all_rows[:n_show]

        # B117: title now includes total impact
        header_suffix = f" ({_signed_total:+.1f} bb/100 across {n_show} leak type{'s' if n_show != 1 else ''})"
        # Replace the basic header we wrote earlier with the enriched one
        # NB: we already wrote the title before this block — overwrite via
        # rendering it again (only the latest is in `doc.lines`).
        # Easier: rewrite the previous "Top leaks" line via doc surgery.
        # The doc.w() above ran already; check if we can pop+rewrite.
        try:
            if doc.lines and doc.lines[-2].startswith("**📌 Top leaks"):
                doc.lines[-2] = f"**📌 Top leaks — notice for next session{header_suffix}:**"
        except Exception:
            pass

        # B116: 4-column table with Impact (BB/100) column
        doc.w("| | Type | Impact | Details |")
        doc.w("|---|---|---|---|")
        for emoji, type_str, details_str, bb100, anchor in all_rows:
            details_safe = details_str.replace('|', '·')
            impact_str = f"**{bb100:+.2f}**" if bb100 is not None else '—'
            type_cell = (f"**{_xref(anchor, label=type_str)}**" if anchor
                         else f"**{type_str}**")
            doc.w(f"| {emoji} | {type_cell} | {impact_str} | {details_safe} |")
        if n_dropped > 0:
            doc.w("")
            doc.w(f"*…and {n_dropped} smaller leak type{'s' if n_dropped != 1 else ''} "
                  f"below the 95% Pareto cutoff (each <"
                  f"{abs(all_rows[-1][3] or 0):.2f} BB/100 impact).*")
        doc.w("")

    # B131c (Ron 2026-05-20): read-dependent calls now render as a bucket row
    # INSIDE the Top Leaks table (see next_session_items append above), not as
    # a separate side block.

    # --- Compact skill / discipline summary ---
    doc.w(f"- **Skill band:** {skill.get('emoji','⚪')} {skill.get('label','—')} "
          f"{_xref('sec-1-1', label='↗')}")
    sb_cum = rd.get('skill_band_cumulative', {})
    if sb_cum.get('available'):
        doc.w(f"- **Cumulative ({sb_cum.get('sessions_used','?')} sessions / "
              f"{sb_cum.get('cum_hands','?')} hands):** {sb_cum.get('emoji','⚪')} "
              f"{sb_cum.get('label','—')} ({sb_cum.get('cum_bb_per_100',0):+.2f} BB/100; "
              f"last-5: {sb_cum.get('last5_bb_per_100',0):+.2f} BB/100)")
    dt = rd.get('discipline_tier', {})
    if dt:
        doc.w(f"- **Discipline tier:** {dt.get('emoji','⚪')} {dt.get('label','—')}")
    # B145 (Ron 2026-05-23): surface punt-rate and mistake-rate in the TL;DR.
    # Punts = analyst-confirmed III.1 (post-override, B148). Mistakes = the
    # non-tail mistake count (tail folds are info-only, excluded by design).
    _n_h_tldr = (s.get('volume', {}) or {}).get('hands', 0) or 1
    _tldr_punts = len(iii1_hands)
    # B222 (Ron review 2026-05-25): the headline mistake count must match
    # III.2 Confirmed Mistakes (= 8: detector CLEAR + analyst-confirmed
    # III.1/III.2). It was reading clear_mistakes_count — the detector-only
    # count (1) — which contradicted III.2's 8. Use the canonical field.
    _tldr_mist = dt.get('canonical_mistakes_count',
                        dt.get('clear_mistakes_count', 0))
    _tldr_mist_p100 = dt.get('canonical_mistakes_per_100',
                             dt.get('mistakes_per_100', 0.0))
    _punt_emoji = '🟢' if _tldr_punts == 0 else ('🟡' if _tldr_punts <= 2 else '🔴')
    doc.w(f"- **Discipline:** {_punt_emoji} PUNTS/100: {100.0*_tldr_punts/_n_h_tldr:.2f} "
          f"({_tldr_punts}) · MISTAKES/100: {_tldr_mist_p100:.2f} "
          f"({_tldr_mist}) {_xref('sec-2', label='↗')}")
    doc.w("")

    # Phase 4.8: Full Result Attribution moved to S1 (Result section) after
    # Per-Tournament P&L. Call _emit_results_attribution(doc, s, rd) from there.
    # The TL;DR now shows only the compact headline; the full breakdown lives
    # in the Result section where it belongs structurally.

    # (dead code removed — see _emit_results_attribution below)

    # --- Original session-read prose, now collapsible (optional context) ---
    synthesis = (rd.get('analyst_commentary', {}) or {}).get('__synthesis__', {})
    if synthesis:
        if synthesis.get('headline'):
            doc.w(f"**🧭 Analyst headline:** {synthesis['headline']}")
            doc.w("")
        if synthesis.get('session_read'):
            doc.w("<details><summary><strong>📝 Full analyst session read</strong></summary>")
            doc.w("")
            doc.w(synthesis['session_read'])
            doc.w("")
            doc.w("</details>")
            doc.w("")
        # B69 REMOVED: "Key signals to carry into next session" — its content
        # is now structurally captured in the "Top leaks — notice for next
        # session" bullets above. The old prose-bullet form was redundant
        # and unstructured. Analyst can still surface synthesis.key_signals
        # as a fallback if the auto-generated top-leaks list is empty.
        if not next_session_items:
            ks = synthesis.get('key_signals', [])
            if ks:
                doc.w("**📌 Key signals to carry into next session:**")
                for sig in ks[:5]:
                    doc.w(f"- {sig}")
                doc.w("")
        # Walk-Backs collapsible — B69: add emoji severity column for skim-ability
        wb = synthesis.get('walk_backs_methodology', {})
        if wb and (wb.get('notes') or wb.get('rows')):
            n_entries = len(wb.get('rows') or wb.get('notes') or [])
            doc.w(f"<details><summary><strong>🔧 {wb.get('title', 'Walk-Backs & Methodology Notes')}</strong> "
                  f"({n_entries} entries — click to expand)</summary>")
            doc.w("")
            if wb.get('rows'):
                # B69 (v7.49): add severity emoji column for visual skim.
                # Heuristic: classify each row by keyword scan of finding text.
                doc.w("| | Hand | Topic | Key Finding |")
                doc.w("|---|---|---|---|")
                for row in wb['rows']:
                    hid = row.get('hand_id') or ''
                    if hid and hid.startswith('TM'):
                        hid_short = hid[-8:]
                        hid_cell = f"[`{hid_short}`](#sec-app-hand-{hid_short})"
                    else:
                        hid_cell = '—'
                    topic = row.get('topic', '—')
                    finding = row.get('key_finding', '—')
                    # Severity classification by keyword
                    finding_lower = (finding or '').lower()
                    if 'iii.1' in finding_lower or 'punt' in finding_lower or 'confirmed' in finding_lower:
                        sev = '🔴'
                    elif ('reclassified' in finding_lower or 'iii.4' in finding_lower
                          or 'iii.3' in finding_lower or 'read-dep' in finding_lower):
                        sev = '🟡'
                    elif ('no walk-back' in finding_lower or 'standard' in finding_lower
                          or 'fine' in finding_lower or 'correct' in finding_lower
                          or 'preflop-only' in finding_lower):
                        sev = '👍'
                    elif ('walk-back' in finding_lower and ('preflop' in finding_lower
                                                            or 'sizing' in finding_lower
                                                            or 'commit' in finding_lower)):
                        sev = '🟠'  # methodology — earlier-action walk-back
                    else:
                        sev = '⚪'
                    doc.w(f"| {sev} | {hid_cell} | {topic} | {finding} |")
            elif wb.get('notes'):
                for note in wb['notes']:
                    doc.w(f"- {note}")
            doc.w("")
            doc.w("**Legend:** 👎 punt · ⚖️ GTO-std · 👍 cleared / justified · "
                  "📖 read-dep · ❄️ cooler · 🟠 walk-back · ⚪ other")
            doc.w("")
            doc.w("</details>")
            doc.w("")
    # Close the legacy-format <details> wrapper opened after the dashboard
    doc.w('')
    doc.w('</details>')
    doc.w('')
    # B186 (Ron review 2026-05-25): TL;DR review row. Now that TL;DR is a proper
    # doc.section("sec-0", ...), the section system handles review. But we still
    # emit a subsection-level review row for the TL;DR content itself so the
    # audit UI can attach a verdict/notes specifically to the executive summary.
    doc.w("<<REVIEWROW|sub|sec-tldr|Summary>>")
    doc.w("---")
    doc.w("")


def _emit_leak_watchlist(doc, s, rd):
    """Daily leak watchlist (Ron 2026-05-14, v7.49.11).

    Renders the top-20 actionable session metrics vs target ranges derived
    from the 64-session May 2026 cohort. Shows status (🟢 / 🟡 / 🔴),
    current value, target range, and action phrase.

    Section design:
      - Header line with summary (n red / n amber / n green)
      - Top priority actions (red + amber priority-1) as a callout
      - Full table at the end
    """
    wl = rd.get('leak_watchlist')
    if not wl or not wl.get('session_metrics'):
        return

    doc.w("## Leak Watchlist")
    doc.w("")
    doc.w(f"*{wl['verdict_line']}*")
    doc.w("")

    # Top priority actions block
    top_actions = wl.get('top_actions', [])
    if top_actions:
        doc.w("**Top priority for this session:**")
        doc.w("")
        for a in top_actions:
            icon = {'red': '🔴', 'amber': '🟡', 'green': '🟢'}.get(a['status'], '⚪')
            _lbl = a.get('label', a['metric'])
            _sec = a.get('section', '')
            if _sec:
                _lbl = f'<a href="#{_sec}" class="xref">{_lbl}</a>'
            doc.w(f"- {icon} **{_lbl}** = {a['value']}{a['arrow']} → {a['action']}")
        doc.w("")

    # Full table — split by status for readability
    doc.w("**Full watchlist** (priority levels: 1 = primary lever, 2 = secondary, 3 = supporting)")
    doc.w("")
    doc.w("| Metric | Value | Target | Window | Status | Pri | Action |")
    doc.w("|---|---:|---|---|:---:|:---:|---|")
    for item in wl['session_metrics']:
        icon = {'red': '🔴', 'amber': '🟡', 'green': '🟢'}.get(item['status'], '⚪')
        window_lbl = 'today' if item['window'] == 'session' else 'trajectory'
        # B-V10: link red/amber metrics to their report section.
        # Use raw HTML <a> (stashed by _md_inline) instead of markdown
        # link syntax — markdown links inside pipe-tables can fail to
        # convert when the label contains parentheses.
        _lbl = item['label']
        _sec = item.get('section', '')
        if _sec and item['status'] in ('red', 'amber'):
            _lbl = f'<a href="#{_sec}" class="xref">{_lbl}</a>'
        doc.w(f"| {_lbl} | {item['value']} | {item['target_range']} | "
              f"{window_lbl} | {icon} | {item['priority']} | {item['action']} |")
    doc.w("")

    # Footer note
    doc.w(f"*Targets derived from May 2026 cohort (64 sessions, 1,090 bullets). "
          f"P25/P75 thresholds; top-quartile-by-logit averages used as 'aim' anchors. "
          f"Refit via gem_meta_analysis.py.*")
    doc.w("")
    doc.w("---")
    doc.w("")


def _emit_results_attribution(doc, s, rd):
    """Full Result Attribution breakdown (was inside _emit_tldr <details>).

    Phase 4.8: extracted to standalone function and called from S1 Result
    after Per-Tournament P&L instead of being buried in the TL;DR.
    Emits as a subsection with its own anchor (sec-1-1a).
    """
    ra = rd.get('results_attribution', {})
    if not ra:
        return

    _summ_scev = ra.get('surface_cev_per_100')
    _summ_icev = ra.get('implied_true_ev_cev_per_100')
    _summ = (f"surface {_summ_scev * 100:+.1f}% → implied "
             f"{_summ_icev * 100:+.1f}% of starting stack /100"
             if _summ_scev is not None and _summ_icev is not None
             else f"surface {ra['surface_bb_per_100']:+.2f} bb/100")
    doc.subsection("sec-1-1a", "S1.1a Full Result Attribution",
                   f"skill vs variance vs mistakes — {_summ}")

    # Item 2: per-day P&L table at the top of S1.1a (same table as S1.0b)
    _day_tbl = _build_daily_pnl_table(rd)
    if _day_tbl:
        _dh, _ds, _dr = _day_tbl
        doc.write_block(financial_table_block(
            "s1-1a-daily", "financial_summary", _dh, _ds, _dr))
        doc.w("")
        # v8.14.1 rev-3 (Blocker 6): this is the by-day financial table that
        # actually renders in the report (the S1.0b daily-summary table is gated
        # out in AUTO_ONLY, so its rev-1 footnote never landed). The Date here is
        # the CASH-SETTLEMENT (session-end) date from the financials export, which
        # can roll to the next calendar day when play runs past midnight — so it
        # may differ from the per-tournament play dates and the report's own date.
        # Label it rather than leave a silent mismatch.
        doc.w("*Date = cash-settlement (session-end) date from the financials "
              "export; it can be the next calendar day when a session runs past "
              "midnight, so it may differ from the per-tournament play dates and "
              "the report date.*")
        doc.w("")
        # v8.14.4 (Ron 2026-06-15): cash + ticket return-basis disclosure on the
        # ACTIVE financial surface. The $Cash column above = settled cash PLUS
        # satellite ticket face value (cash_total), and $Net / ROI derive from it,
        # so the basis must be stated. The v8.14.3 footnote was placed in
        # _emit_daily_summary_table, which only renders from the DISABLED S7 Coach
        # section (commented out of draft.py's render list), so it never reached
        # the report — this is the by-day table that actually renders (S1.1a).
        # Canonical source: usd_overlay.totals.total_ticket_value; shown only when
        # ticket value > 0 (no math change, no analyst-content change).
        _ov_tot_v144 = (rd.get('usd_overlay') or {}).get('totals') or {}
        _tick_v144 = _ov_tot_v144.get('total_ticket_value') or 0
        if _tick_v144 > 0:
            doc.w(f"*$Cash / Return = settled cash **plus** satellite ticket value "
                  f"(${_tick_v144:,.2f} in tickets); $Net and ROI use this "
                  f"cash + ticket basis, not cash only.*")
            doc.w("")

    # B211 (Ron review 2026-05-25): the human guide to reading this
    # breakdown lives here, next to the data it explains.
    _si_ag = ((rd.get('analyst_commentary', {}) or {}).get('__synthesis__', {})
              or {}).get('session_interpretation', {})
    if isinstance(_si_ag, dict) and _si_ag.get('attribution_guide'):
        doc.w(f"*{_si_ag['attribution_guide']}*")
        doc.w("")
    vcev = rd.get('variance_cev', {}) or {}
    cev_sess = rd.get('cev_session', {}) or {}
    _surf_cev_total = cev_sess.get('cev_per_stack_total')
    _surf_cev = cev_sess.get('cev_per_stack_per_100')
    _cap_cev = (f" Accumulated cEV this session: "
                f"{_surf_cev_total:+.2f} starting stacks "
                f"({cev_sess.get('net_chips_total', 0):+,.0f} chips)."
                if _surf_cev_total is not None else "")

    def _cevcell(cev):
        # cev is a fraction-of-starting-stack rate; show as XX.X%.
        return f"{cev * 100:.1f}%" if cev is not None else '—'

    def _ratiocell(bb100, cev):
        if cev is None or abs(cev) < 1e-9:
            return '—'
        return f"{bb100 / (cev * 10):.1f}"

    # v8.14.1 hotfix (#1 dense-copy): lead with the concise numbers; the
    # BB-vs-cEV technical caveat moves into a collapsible <details> so it no
    # longer dominates the page (replaced the old dense surface paragraph;
    # this is NOT an additional gloss).
    doc.w(f"*cEV {_cevcell(_surf_cev)} of starting stack /100 over "
          f"{ra['n_hands']} hands "
          f"({cev_sess.get('n_resolved', 0)} of "
          f"{(cev_sess.get('n_resolved', 0) + cev_sess.get('n_unresolved', 0))} "
          f"tournaments resolved); BB/100 {ra['surface_bb_per_100']:+.2f}.{_cap_cev}*")
    doc.w("")
    doc.w("<details><summary>Why cEV, not BB/100?</summary>")
    doc.w("")
    doc.w("BB/100 does not aggregate across tournaments at different blind "
          "levels — a stack built at low blinds then lost at high blinds reads "
          "BB-positive on a chip loss — so cEV (chip-EV as % of starting stack) "
          "is the reconciling spine metric.")
    doc.w("")
    doc.w("</details>")
    doc.w("")

    # B-V10: technical columns (spine, BB/cEV) only for Ron — other players
    # find them confusing. Gate on player_name containing 'knock' (case-insensitive).
    _is_ron = 'knock' in (rd.get('player_name') or '').lower()
    # v8.12.4 (QA item 8): when the headline BB/100 and the cEV spine point
    # in OPPOSITE directions, say so up front instead of letting the
    # dashboard tell a winning story and this table a losing one.
    _surf_bb100_rec = ra.get('surface_bb_per_100', 0) or 0
    if (_is_ron and _surf_cev is not None and abs(_surf_cev) > 5
            and abs(_surf_bb100_rec) > 1
            and (_surf_cev > 0) != (_surf_bb100_rec > 0)):
        doc.w(f"⚖️ **The two spines disagree on this session** — BB/100 says "
              f"**{_surf_bb100_rec:+.1f}** (winning) while %-of-starting-stack "
              f"says **{_surf_cev:+.1f}%/100** (losing). Both are correct: "
              f"BB/100 weights every hand by its CURRENT blind level, so "
              f"chips won at big late-game blinds count for few BB lost "
              f"early; the cEV spine weights by tournament starting stacks, "
              f"so every bust-out burns a full stack. A late-reg-heavy, "
              f"bust-heavy session with a few deep runs produces exactly "
              f"this split. The dashboard quotes BB/100; this ledger uses "
              f"the cEV spine — read the rows below in cEV terms.")
        doc.w("")
    if _is_ron:
        doc.w("| Component | % Starting Stack / 100 (spine) | BB/100 (ref) | BB/cEV | Direction |")
        doc.w("|---|---|---|---|---|")
        doc.w(f"| Surface result | {_cevcell(_surf_cev)} | "
              f"{ra['surface_bb_per_100']:+.2f} | "
              f"{_ratiocell(ra['surface_bb_per_100'], _surf_cev)} | — |")
    else:
        doc.w("| Component | BB/100 | Direction |")
        doc.w("|---|---|---|")
        doc.w(f"| Surface result | "
              f"{ra['surface_bb_per_100']:+.2f} | — |")
    # Helper: emit a row with or without technical columns
    def _ra_row(comp, cev_val, bb100, ratio_bb, ratio_cev, direction, bold=False):
        b = '**' if bold else ''
        if _is_ron:
            doc.w(f"| {b}{comp}{b} | {b}{_cevcell(cev_val)}{b} | "
                  f"{b}{bb100:+.2f}{b} | {_ratiocell(bb100, cev_val)} | {direction} |")
        else:
            doc.w(f"| {b}{comp}{b} | {b}{bb100:+.2f}{b} | {direction} |")

    # v8.12.4 (QA item 7): direction labels key off the SPINE (cEV) when it
    # is available — the section explicitly declares cEV authoritative. A
    # -64.5% cEV row was labeled "variance HELPED" because the label keyed
    # off the BB/100 reference column. When the two disagree in sign, say so
    # instead of picking a side.
    def _dir3(cev_val, bb_val, hurt_lbl, helped_lbl):
        if cev_val is not None and abs(cev_val) > 1 and bb_val is not None \
                and abs(bb_val) > 1 and (cev_val > 0) != (bb_val > 0):
            _c = hurt_lbl if cev_val < 0 else helped_lbl
            _b = helped_lbl if cev_val < 0 else hurt_lbl
            return f"mixed — cEV: {_c} / BB: {_b}"
        _key = cev_val if cev_val is not None else bb_val
        if _key is None:
            return 'neutral'
        if _key < -1:
            return hurt_lbl
        if _key > 1:
            return helped_lbl
        return 'neutral'

    cq_bb = ra.get('card_quality_var_bb', 0)
    cq_dir = ('ran hot on cards' if cq_bb > 1
              else ('ran cold on cards' if cq_bb < -1 else 'neutral'))
    cq_delta_pp = ra.get('card_quality_delta_pp', 0)
    _cq_p100 = ra.get('card_quality_var_per_100', 0)
    _cq_cev = (vcev.get('card_quality') or {}).get('cev_per_100')
    _ra_row(f"[Card quality](#sec-1-5) ({cq_delta_pp:+.1f}pp premium delta)",
            _cq_cev, _cq_p100, _cq_p100, _cq_cev, cq_dir)
    mh_bb = ra.get('made_hands_var_bb', 0)
    mh_dir = ('boards cooperated' if mh_bb > 1
              else ('boards bricked' if mh_bb < -1 else 'neutral'))
    _mh_p100 = ra.get('made_hands_var_per_100', 0)
    _mh_cev = (vcev.get('made_hands') or {}).get('cev_per_100')
    _ra_row("[Made hands vs expected](#sec-1-6)",
            _mh_cev, _mh_p100, _mh_p100, _mh_cev, mh_dir)
    co_bb = ra.get('cooler_var_bb', 0)
    co_actual = ra.get('cooler_count_actual', 0)
    co_expected = ra.get('cooler_count_expected', 0)
    co_dir = ('cooled less than expected' if co_bb > 1
              else ('coolered more than expected' if co_bb < -1 else 'neutral'))
    _co_p100 = ra.get('cooler_var_per_100', 0)
    _co_cev = (vcev.get('cooler') or {}).get('cev_per_100')
    _ra_row(f"[Cooler frequency](#sec-1-7) ({co_actual} actual vs {co_expected:.1f} expected)",
            _co_cev, _co_p100, _co_p100, _co_cev, co_dir)
    _eai_p100 = ra['eai_variance_per_100']
    _eai_cev = (vcev.get('eai') or {}).get('cev_per_100')
    var_dir = _dir3(_eai_cev if _is_ron else None, ra['eai_variance_bb'],
                    'variance HURT', 'variance HELPED')
    _ra_row("[All-in variance](#sec-1-4)",
            _eai_cev, _eai_p100, _eai_p100, _eai_cev, var_dir)
    # v8.12.4 (QA item 6): the refresh hook folds analyst III.1/III.2 EV
    # (hand net_bb — same figure the S2.2 table shows) into the row, and the
    # count is the canonical discipline-tier count, so this row can no
    # longer say "1 confirmed, +0.00" while S2.2 says "2 confirmed, ~92BB".
    if ra.get('mistake_row_count') is not None:
        _mist_total = ra['mistake_row_count']
        _mist_p100 = ra.get('mistake_row_per_100', ra['non_tail_mistake_per_100'])
        _mist_cev = ra.get('mistake_row_cev_per_100',
                           ra.get('non_tail_mistake_cev_per_100'))
    else:
        mist_n = ra.get('non_tail_mistake_count', 0)
        _mist_p100 = ra['non_tail_mistake_per_100']
        _mist_cev = ra.get('non_tail_mistake_cev_per_100')
        _ac_b211 = rd.get('analyst_commentary', {}) or {}
        _det_ids_b211 = {m.get('id') for m in (s.get('mistakes', []) or [])}
        _mist_extra = sum(
            1 for _h, _c in (_ac_b211.items() if isinstance(_ac_b211, dict) else [])
            if isinstance(_c, dict)
            and (_c.get('verdict', '') or '').startswith(('III.1', 'III.2'))
            and _h not in _det_ids_b211)
        _mist_total = mist_n + _mist_extra
    _ra_row(f"[Mistake-EV](#sec-2-1) ({_mist_total} confirmed)",
            _mist_cev, _mist_p100, _mist_p100, _mist_cev,
            "mistakes HURT (excl. tail folds)")
    tail_n = ra.get('tail_fold_count', 0)
    if tail_n:
        _tail_p100 = ra['tail_fold_per_100']
        _tail_cev = ra.get('tail_fold_cev_per_100')
        _ra_row(f"[Tail folds](#sec-2-1) ({tail_n} info-only)",
                _tail_cev, _tail_p100, _tail_p100, _tail_cev,
                "not a leak (mixed strategy)")
    _itev_cev = ra.get('implied_true_ev_cev_per_100')
    _ceil_cev = ra.get('implied_ceiling_cev_per_100')
    _itev_p100 = ra.get('implied_true_ev_extended_per_100', 0)
    _ceil_p100 = ra.get('implied_ceiling_extended_per_100', 0)
    _ra_row("True EV (all variance adj)",
            _itev_cev, _itev_p100, _itev_p100, _itev_cev, "skill", bold=True)
    _ra_row("Implied perfect-play ceiling",
            _ceil_cev, _ceil_p100, _ceil_p100, _ceil_cev,
            "skill + no mistakes", bold=True)

    # --- Residual decomposition (v7.62)
    _rdec = rd.get('residual_decomposition', {}) or {}
    if _rdec.get('available'):
        _rdd = _rdec['read_dependent']
        _mm = _rdec['mda_missed']
        _ma = _rdec['mda_aligned']
        _un = _rdec['unattributed']
        # FEAT-1: row-name tooltips replace the body-text explanations
        _tip_rd = ("This session&#39;s river bluff-catches, priced against "
                   "the pool. Solver-real — each call valued by equity vs "
                   "population calling range.")
        _tip_mm = ("Generic per-recommendation EV from the 2.1M-hand dataset "
                   "(same basis as card-quality layer). De-duped against "
                   "Mistake-EV so no leak is subtracted twice.")
        _tip_ma = ("Credit for exploits Hero executed that aligned with "
                   "model-expected adjustments. Same MDA basis as missed.")
        _tip_un = ("Balancing remainder the pipeline cannot yet attribute "
                   "to a named cause. A large figure means a detector is "
                   "missing, not that the play was fine.")
        doc.w("| *— what's inside the residual —* | | | | |")
        doc.w(f'| <span data-tip="{_tip_rd}">Read-dependent (pool miscalibration)</span> | '
              f"{_cevcell(_rdd.get('cev_per_100'))} | {_rdd['per_100']:+.2f} | "
              f"{_ratiocell(_rdd['per_100'], _rdd.get('cev_per_100'))} | "
              f"{_rdd['n_calls']} call(s), solver-real |")
        _dd = (f", {_mm['n_deduped']} deduped vs Mistake-EV"
               if _mm['n_deduped'] else "")
        doc.w(f'| <span data-tip="{_tip_mm}">MDA exploits missed</span> | '
              f"{_cevcell(_mm.get('cev_per_100'))} | "
              f"{_mm['per_100']:+.2f} | "
              f"{_ratiocell(_mm['per_100'], _mm.get('cev_per_100'))} | "
              f"{_mm['n_events']} event(s){_dd}, model-expected |")
        doc.w(f'| <span data-tip="{_tip_ma}">MDA exploits aligned (credit)</span> | '
              f"{_cevcell(_ma.get('cev_per_100'))} | {_ma['per_100']:+.2f} | "
              f"{_ratiocell(_ma['per_100'], _ma.get('cev_per_100'))} | "
              f"{_ma['n_events']} event(s), model-expected |")
        doc.w(f'| <span data-tip="{_tip_un}">**Unattributed**</span> | '
              f"**{_cevcell(_un.get('cev_per_100'))}** | "
              f"**{_un['per_100']:+.2f}** | — | un-named leak cost |")
    doc.w("")
    if _rdec.get('available'):
        if _rdec.get('low_confidence'):
            doc.w("⚠️ **Low-confidence decomposition** — the named layers "
                  "(read-dependent, MDA) explain less than half the skill "
                  "residual. The Unattributed row is a balancing plug, not "
                  "a measured value. This is normal for sessions with few "
                  "river showdowns or few model-actionable spots; it means "
                  "the pipeline cannot yet attribute most of the skill signal "
                  "to a named cause.")
            doc.w("")
        # FEAT-1: explanatory text moved into data-tip tooltips on the
        # row names above. The "what this block is" intro stays as a
        # compact one-liner so the reader still knows how to read it.
        doc.w("📐 *The four rows above break down the True EV skill "
              "residual — hover each row name for methodology. They do "
              "not extend the subtraction chain.*")
    doc.w("")
    # Phase 4.8 v3: methodology text → tooltip on a single "Methodology" label
    _meth_tip = (
        "Why cEV is the spine: a big blind is a different chip amount at "
        "every level, so net-BB does not sum across an MTT session. "
        "% Starting Stack / 100 divides every chip amount by the starting "
        "stack of its tournament — it sums correctly and matches financial "
        "direction. BB/100 is kept only as a familiar, blind-weighted "
        "reference. Scope: this is chip-EV, not money — ICM is separate. "
        "How layers are derived: All-in variance = realized-minus-expected "
        "chip swing vs equity-category baselines. Cooler = actual average "
        "chip loss × count deviation. Made-hands = conversion-gap module. "
        "Mistake-EV / Tail folds = each flag's EV converted by its hand's "
        "big blind then divided by starting stack. Card quality = "
        "premium-count deviation × per-premium expected value. Implied "
        "rows = derived by subtraction so the ledger balances. BB/cEV is "
        "a coarse sanity ratio only — treat divergent values as expected.")
    doc.w(f'<span data-tip="{_meth_tip}">*ⓘ Methodology — why cEV is '
          f'the spine (hover for details)*</span>')
    doc.w("")
    # B46 (v7.51): Stack-tier loss breakdown
    n_deep_l = ra.get('n_deep_losses', 0)
    n_mid_l = ra.get('n_mid_losses', 0)
    n_short_l = ra.get('n_short_losses', 0)
    if (n_deep_l + n_mid_l + n_short_l) > 0:
        doc.w(f"*Stack-tier impact of large losses (>25BB hands), B46:* "
              f"the standard variance decomp treats every BB equal, but losses "
              f"at deep stacks carry more weight psychologically and "
              f"chip-EV-wise.")
        doc.w("")
        doc.w("| Tier | Hands | Total loss (BB) | Worst single |")
        doc.w("|---|---|---|---|")
        worst_deep = ra.get('worst_deep_loss_hands', []) or []
        worst_id = (f"[`{worst_deep[0]['id'][-8:]}`](#sec-app-hand-{worst_deep[0]['id'][-8:]}) "
                    f"({worst_deep[0]['net_bb']:+.1f})" if worst_deep else "—")
        worst_mid = ra.get('worst_mid_loss_hands', []) or []
        worst_mid_id = (f"[`{worst_mid[0]['id'][-8:]}`](#sec-app-hand-{worst_mid[0]['id'][-8:]}) "
                        f"({worst_mid[0]['net_bb']:+.1f})" if worst_mid else "—")
        worst_short = ra.get('worst_short_loss_hands', []) or []
        worst_short_id = (f"[`{worst_short[0]['id'][-8:]}`](#sec-app-hand-{worst_short[0]['id'][-8:]}) "
                          f"({worst_short[0]['net_bb']:+.1f})" if worst_short else "—")
        doc.w(f"| Deep (≥50BB eff) | {n_deep_l} | {ra.get('deep_loss_bb', 0):+.1f} "
              f"({ra.get('deep_loss_share', 0)*100:.0f}% of neg variance) | {worst_id} |")
        doc.w(f"| Mid (20-50BB eff) | {n_mid_l} | {ra.get('mid_loss_bb', 0):+.1f} | {worst_mid_id} |")
        doc.w(f"| Short (<20BB eff) | {n_short_l} | {ra.get('short_loss_bb', 0):+.1f} | {worst_short_id} |")
        doc.w("")
        concentration = ra.get('deep_concentration', 'low')
        if concentration == 'high':
            doc.w(f"**Concentration: 🔴 HIGH.** >60% of negative variance came from "
                  f"deep-stack hands. This is the 'felt brutal' signature — variance "
                  f"frequency may be normal but the IMPACT was concentrated where "
                  f"each loss matters most. Worth flagging to mental-game.")
            doc.w("")
        elif concentration == 'moderate':
            doc.w(f"**Concentration: 🟡 MODERATE.** Deep-stack losses account for "
                  f"{ra.get('deep_loss_share', 0)*100:.0f}% of negative variance.")
            doc.w("")
    if ra.get('overfit_warning'):
        _ofs = ra.get('overfit_ratio_spine')
        _surf_sp = ra.get('surface_cev_per_100')
        _var_sp = ra.get('total_variance_cev_per_100')
        if _ofs is not None and _surf_sp is not None and _var_sp is not None:
            doc.w(f"⚠️ **Overfit warning:** on the spine (% starting stack), "
                  f"total variance corrections ({_var_sp*100:+.1f}%/100) are "
                  f"{_ofs:.1f}× the surface result ({_surf_sp*100:+.1f}%/100) — "
                  f"past the 2× guard. The True EV figure is mostly variance "
                  f"attribution, not a robust skill estimate; treat it as a "
                  f"hypothesis, not a verdict.")
        else:
            doc.w(f"⚠️ **Overfit warning:** variance corrections exceed 2× the "
                  f"surface result. Treat the True EV with caution.")
        doc.w("")
    doc.w("")


def _emit_legend(doc):
    doc.w("## Legend")
    doc.w("")
    doc.w("| Symbol | Meaning |")
    doc.w("|---|---|")
    doc.w("| 🟢 | In target (CI overlaps target band) |")
    doc.w("| 🟡 | Borderline (CI doesn't overlap, but rate within 1 spread) |")
    doc.w("| 🔴 | Out of target (rate >1 spread outside band) |")
    doc.w("| ⚪ | Sample too small (n<10 typically) |")
    doc.w("| 👍 | Normal/fine, mentioned for completeness |")
    doc.w("| 🆕 | New leak this session |")
    doc.w("| ↗️ | Recurring leak (2+ sessions) |")
    doc.w("| ⚠️ | Pipeline bug noted — see Section X |")
    doc.w("")
    doc.w("**Numbering:** Roman major (I-XIII), decimal subsections.")
    doc.w("")
    doc.w("**Verdict logic:** Wilson 90% CI computed for each rate. "
          "🟢 if CI overlaps target band; 🔴 if observed rate is more than one "
          "band-width outside; 🟡 between; ⚪ if sample n<10.")
    doc.w("")
    doc.w("**Hand citation format:** `id-suffix` • Tournament (date) • Position StackBB. "
          "Applied to every hand reference per v7.35 D19 rule.")
    doc.w("")


# ============================================================
# SECTION I — REALITY CHECK
# ============================================================

