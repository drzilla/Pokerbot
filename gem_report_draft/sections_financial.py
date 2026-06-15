"""Sections I (Volume & Results) and II (Core Stats) emitters."""

from gem_report_draft import _state
from gem_report_draft._helpers import (_wilson_ci, _clr, _clr_min, _clr_naive,
    _pctc, _stat_signal, _verdict_ci, _verdict_pct, _hand_ref, _hand_ref_short,
    _xref, _stat_row, _stat_row_pct, _aim_lookup_from_watchlist, _back_to_kpis,
    _compact_range, _run_emoji, _outcome_label, _CI_Z_DEFAULT, _MIN_N_FOR_SIGNAL,
    _RANK_ORD, _break_at_sentences, _href, _emit_correct_ranges, _new_badge,
    _hand_ref_id_only)
from gem_report_draft._html import (Doc, _card_html, _cards_html,
    _cards_str_to_pills, _cards_text_to_pills, _md_inline, _html_escape,
    _sort_cards_desc, _describe_made_hand, _SUIT_HTML, _RANK_VALUES, _SUIT_VALUES)
from gem_report_draft._blocks import (financial_table_block,
    variance_ledger_block, hand_evidence_table_block, metric_table_block)
from gem_report_draft._hand_grid import (_render_hand_grid_table,
    _key_decision_action_class, _pick_key_action_idx, _hero_actions_by_street_from_app,
    _hero_action_verbs_by_street_from_app, _verdict_display_label)
from gem_report_draft.sections_xiv import (_eai_one_liner, _per_tourney_one_liner,
    _short_tournament, _generate_cheat_sheet)
from gem_report_draft.sections_mistakes import _emit_mental_game

import gem_made_hands as mh


def _fmt_usd(v, plus=False):
    """B-AVIEL BUG-4: format a USD amount — show cents when fractional, whole
    otherwise.  `plus=True` adds a '+' sign for positives."""
    if v is None:
        return '—'
    fmt = f"{v:+.2f}" if plus else f"{v:.2f}"
    # Strip ".00" for whole amounts
    if fmt.endswith('.00'):
        fmt = fmt[:-3]
    return f"${fmt}"


def _build_daily_pnl_table(rd):
    """Build per-day financial table rows. Returns (header, sep, rows) or None.

    Shared by S1.0b Daily Summary and S1.1a per-day table at top of
    Full Result Attribution (Item 2).
    """
    usd = rd.get('usd_overlay') or {}
    per_t = usd.get('per_tournament') or []
    if not per_t:
        return None

    # Aggregate by start_date
    from collections import defaultdict
    by_date = defaultdict(lambda: {
        'n_t': 0, 'n_b': 0, 'cost': 0.0, 'cash': 0.0,
        'itm_bullets': 0, 't1': 0, 't5': 0, 'ft': 0,
    })
    for t in per_t:
        d = t.get('start_date') or ''
        if not d: continue
        a = by_date[d]
        a['n_t'] += 1
        a['n_b'] += t.get('bullets', 1)
        a['cost'] += t.get('cost', 0.0)
        a['cash'] += t.get('cash_total', 0.0)
        if t.get('itm'): a['itm_bullets'] += t.get('bullets', 1)
        place = t.get('place', 0)
        total = t.get('total_players', 0)
        is_sat = t.get('is_sat', False)
        if total > 0:
            pctile = place / total * 100
            if pctile <= 1.0 or place == 1: a['t1'] += 1
            if pctile <= 5.0 or place <= 3: a['t5'] += 1
            if 1 <= place <= 9 and not is_sat:
                a['ft'] += 1

    if not by_date:
        return None

    # B135: collapse two adjacent GG dates into one Bangkok-time session
    # ONLY when they share the same session_history Date (truly one session
    # straddling midnight). Multi-day reports should show each day separately.
    _sh_date = (rd.get('session_history_row') or {}).get('Date', '')
    if len(by_date) == 2 and _sh_date:
        from datetime import datetime as _dt
        _ds = sorted(by_date.keys())
        try:
            _delta = (_dt.strptime(_ds[1], '%Y-%m-%d')
                      - _dt.strptime(_ds[0], '%Y-%m-%d')).days
            # Only collapse if 1 day apart AND the session_history says it's
            # a single session (same Date). Multi-day batches keep separate rows.
            if _delta == 1 and _sh_date in (_ds[0], _ds[1]):
                _merged = dict(by_date[_ds[0]])
                for _k, _v in by_date[_ds[1]].items():
                    _merged[_k] = _merged.get(_k, 0) + _v
                by_date = {_sh_date: _merged}
        except Exception:
            pass

    _fs_header = ("| Date | Tourneys | Bullets | $Cost | $Cash | $Net | ROI | "
                  "ITM/B | Top1/B | Top5/B | FT/B | Avg BI |")
    _fs_sep = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    _fs_rows = []
    overall_cost = 0; overall_cash = 0; overall_n_t = 0; overall_n_b = 0
    overall_itm = 0; overall_t1 = 0; overall_t5 = 0; overall_ft = 0
    for date in sorted(by_date.keys()):
        a = by_date[date]
        net = a['cash'] - a['cost']
        roi = (net / a['cost'] * 100) if a['cost'] > 0 else 0
        itm_pct = (a['itm_bullets'] / a['n_b'] * 100) if a['n_b'] else 0
        t1_pct = (a['t1'] / a['n_b'] * 100) if a['n_b'] else 0
        t5_pct = (a['t5'] / a['n_b'] * 100) if a['n_b'] else 0
        # FT/B uses n_b (same denominator as all other /B metrics).
        # Was using mtt_b_for_ft which excluded tournaments without placement
        # data, making FT/B=100% when only 1 of 11 bullets had data.
        ft_pct = (a['ft'] / a['n_b'] * 100) if a['n_b'] else 0
        avg_bi = (a['cost'] / a['n_b']) if a['n_b'] else 0
        net_emoji = '🟢' if net > 0 else ('🔴' if net < -50 else '🟡')
        _fs_rows.append(
            f"| {date} | {a['n_t']} | {a['n_b']} | "
            f"{_fmt_usd(a['cost'])} | {_fmt_usd(a['cash'])} | {net_emoji} **{_fmt_usd(net, plus=True)}** | "
            f"{roi:+.1f}% | {itm_pct:.1f}% | {t1_pct:.1f}% | {t5_pct:.1f}% | "
            f"{ft_pct:.1f}% | {_fmt_usd(avg_bi)} |")
        overall_cost += a['cost']; overall_cash += a['cash']
        overall_n_t += a['n_t']; overall_n_b += a['n_b']
        overall_itm += a['itm_bullets']; overall_t1 += a['t1']
        overall_t5 += a['t5']; overall_ft += a['ft']

    # Total row (always — even for single day, per Item 2 spec)
    net = overall_cash - overall_cost
    roi = (net / overall_cost * 100) if overall_cost > 0 else 0
    itm_pct = (overall_itm / overall_n_b * 100) if overall_n_b else 0
    t1_pct = (overall_t1 / overall_n_b * 100) if overall_n_b else 0
    t5_pct = (overall_t5 / overall_n_b * 100) if overall_n_b else 0
    ft_pct = (overall_ft / overall_n_b * 100) if overall_n_b else 0
    avg_bi = (overall_cost / overall_n_b) if overall_n_b else 0
    net_emoji = '🟢' if net > 0 else ('🔴' if net < -50 else '🟡')
    _fs_rows.append(
        f"| **Total** | **{overall_n_t}** | **{overall_n_b}** | "
        f"**{_fmt_usd(overall_cost)}** | **{_fmt_usd(overall_cash)}** | "
        f"{net_emoji} **{_fmt_usd(net, plus=True)}** | **{roi:+.1f}%** | "
        f"**{itm_pct:.1f}%** | **{t1_pct:.1f}%** | **{t5_pct:.1f}%** | "
        f"**{ft_pct:.1f}%** | **{_fmt_usd(avg_bi)}** |")

    return (_fs_header, _fs_sep, _fs_rows)


def _emit_daily_summary_table(doc, rd):
    """B49 (v7.53, Ron 2026-05-18): Daily summary table.

    Combines USD financial reality (from usd_overlay) with hand-history
    skill metrics (BB/100, skill_index, mistakes/100) per day.

    Surfaces what the user asked for in v7.53 spec:
    - # bullets per day
    - Total $ in / out / profit, ROI
    - ITM%/B, Top1%/B, Top5%/B
    - BB/100
    - Skill level + direction arrow (↑ if today > anchor, ↓ if below, → flat)

    Timezone caveat (per Ron): GG game-summary dates may differ from
    Bangkok-time HH dates by a few hours. The table groups by the
    summary's start_date as authoritative. A footnote calls this out.
    """
    _tbl = _build_daily_pnl_table(rd)
    if _tbl is None:
        return

    # Pull skill_index from session_history for direction arrow
    sh_row = (rd.get('session_history_row') or {})
    sm = rd.get('skill_movement') or {}
    today_skill = (sm.get('today') or {}).get('skill_index')
    anchor_skill = (sm.get('anchor') or {}).get('skill_index')
    bb100 = sh_row.get('BB_per_100') if isinstance(sh_row, dict) else None
    mistakes_per_100 = sh_row.get('Mistakes_per_100') if isinstance(sh_row, dict) else None
    if bb100 is None:
        # Try via stats core
        core = rd.get('_core_for_table') or {}
        bb100 = core.get('bb_per_100')

    doc.subsection("sec-1-0b", "S1.0b Daily Summary",
                   "by-day P&L + skill — both pictures side-by-side")
    doc.w("*Note: presented as a single Bangkok-time session — the timezone "
          "PokerCraft uses. GG game-summary start times can straddle two GG/UTC "
          "calendar dates; a session that does is collapsed back into the one "
          "Bangkok-time playing session it actually was.*")
    doc.w("")

    _fs_header, _fs_sep, _fs_rows = _tbl
    _fs_blk = financial_table_block("daily-summary", "financial_summary",
                                    _fs_header, _fs_sep, _fs_rows)
    doc.write_block(_fs_blk)
    doc.w("")
    # v8.14.1 hotfix (#6 date mismatch): the financials export keys aggregates by
    # CASH-SETTLEMENT date (session-end), which can roll to the next calendar day
    # when a session runs past midnight — so this Date may differ from the
    # per-tournament play dates and the report date. Label it rather than leave a
    # silent mismatch.
    doc.w("*Date column = cash-settlement (session-end) date from the financials "
          "export; it can be the next calendar day when play runs past midnight, "
          "so it may differ from the per-tournament play dates and the report date.*")
    doc.w("")
    # v8.14.3 Issue 1 (Ron 2026-06-15): cash basis disclosure. $Cash = settled
    # cash + satellite ticket value (cash + ticket); Net/ROI use that basis. State
    # it visibly so the cash+ticket total is never read as a cash-only figure.
    _ov_tot_fin = (rd.get('usd_overlay') or {}).get('totals') or {}
    _tick_fin = _ov_tot_fin.get('total_ticket_value') or 0
    if _tick_fin and _tick_fin > 0:
        doc.w(f"*$Cash = settled cash **+ satellite ticket value** (cash + ticket; "
              f"includes {_fmt_usd(_tick_fin)} in tickets). Net/ROI use this "
              f"cash+ticket basis, not cash-only.*")
        doc.w("")

    # Skill picture in a second small table
    skill_lines = []
    if bb100 is not None:
        try:
            bb_val = float(bb100)
            bb_arrow = '↑' if bb_val > 0.5 else ('↓' if bb_val < -0.5 else '→')
            skill_lines.append(f"- **BB/100 (surface):** {bb_val:+.2f} {bb_arrow}")
        except (ValueError, TypeError):
            pass
    ra = rd.get('results_attribution') or {}
    if ra.get('implied_true_ev_extended_per_100') is not None:
        iev = ra['implied_true_ev_extended_per_100']
        ev_arrow = '↑' if iev > 0.5 else ('↓' if iev < -0.5 else '→')
        skill_lines.append(f"- **True EV (variance-adjusted):** {iev:+.2f} bb/100 {ev_arrow}")
    if mistakes_per_100 is not None:
        try:
            mv = float(mistakes_per_100)
            skill_lines.append(f"- **Mistakes/100:** {mv:.2f}")
        except (ValueError, TypeError):
            pass
    if today_skill is not None and anchor_skill is not None:
        try:
            ts = float(today_skill); ans = float(anchor_skill)
            delta = ts - ans
            arrow = '↑' if delta > 5 else ('↓' if delta < -5 else '→')
            sign = '+' if delta > 0 else ''
            skill_lines.append(f"- **Skill Index:** {ts:.0f} (vs anchor {ans:.0f}, "
                                 f"{sign}{delta:.0f}) {arrow}")
        except (ValueError, TypeError):
            pass

    if skill_lines:
        doc.w("**Skill picture (HH-derived):**")
        doc.w("")
        for line in skill_lines:
            doc.w(line)
        doc.w("")


def _emit_skill_index_movement(doc, rd):
    """Render the skill_index movement block (Ron 2026-05-16).

    Source: rd['skill_movement'] (populated by prepare_report_data when
    per-tournament history is available). Renders as section I.0 — placed
    at the top of Section I because it's the highest-leverage summary
    of "did the session move my long-term skill measure?"
    """
    mv = rd.get('skill_movement')
    if not mv:
        return
    anchor = mv.get('anchor')
    responsive = mv.get('responsive')
    today = mv.get('today')
    if not (anchor and responsive):
        return  # need at least the two trailing windows

    doc.w("<details><summary><strong>S1.0 Skill Index / Model Details</strong> — "
          "where today landed vs. trailing baselines</summary>")
    doc.w("")
    doc.w("| Window | skill_index | 95% CI | n_tnys / n_bullets | FinScore |")
    doc.w("|---|---:|---|---:|---:|")
    doc.w(f"| Long-term anchor (500b trailing) | **{anchor['skill_index']}** | "
          f"[{anchor['skill_index_ci_low']}, {anchor['skill_index_ci_high']}] | "
          f"{anchor['n_t']} / {anchor['n_b']} | {anchor['fin_score']:.1f}% |")
    doc.w(f"| Responsive (100-tny trailing) | **{responsive['skill_index']}** | "
          f"[{responsive['skill_index_ci_low']}, {responsive['skill_index_ci_high']}] | "
          f"{responsive['n_t']} / {responsive['n_b']} | {responsive['fin_score']:.1f}% |")
    if today:
        warn = ' ⚠ low sample' if mv.get('today_low_sample') else ''
        doc.w(f"| **Today**{warn} | **{today['skill_index']}** | "
              f"[{today['skill_index_ci_low']}, {today['skill_index_ci_high']}] | "
              f"{today['n_t']} / {today['n_b']} | {today['fin_score']:.1f}% |")
    deltas = mv.get('deltas', {})
    if deltas:
        doc.w("")
        movement_bits = []
        if 'today_vs_anchor' in deltas:
            d = deltas['today_vs_anchor']
            movement_bits.append(f"vs anchor: **{d:+}**")
        if 'today_vs_responsive' in deltas:
            d = deltas['today_vs_responsive']
            movement_bits.append(f"vs responsive: **{d:+}**")
        if 'responsive_vs_anchor' in deltas:
            d = deltas['responsive_vs_anchor']
            movement_bits.append(f"responsive vs anchor: {d:+}")
        if movement_bits:
            doc.w("**Movement (ELO):** " + " · ".join(movement_bits))

    # Skill_Index sparkline — last 5 sessions, day-to-day (high noise: σ≈86 ELO)
    sparks = rd.get('trend_sparklines', {})
    si_spark = sparks.get('Skill_Index')
    if si_spark and si_spark.get('values') and len(si_spark['values']) >= 2:
        vals = si_spark['values']
        trend_str = ' → '.join(f'{v:.0f}' for v in vals[-5:])
        doc.w("")
        doc.w(f"**Skill_Index last 5 sessions:** {trend_str} {si_spark.get('direction','')}")
        doc.w("> *Day-to-day SD ≈ 86 ELO — single-session swings are mostly variance, not skill drift.*")
    # Handicap-confidence warning
    for window_dict in (today, responsive, anchor):
        if window_dict and window_dict.get('handicap_warning'):
            doc.w("")
            doc.w(f"> ⚠ {window_dict['handicap_warning']}")
            break
    doc.w("")

    # Per-tier breakdown
    per_tier = mv.get('today_per_tier', {})
    if per_tier:
        doc.subsection("sec-1-0a", "S1.0a Today's Tier Breakdown",
                       "which buckets contributed how")
        doc.w("| Tier | n_t | n_b | Vol % | FinScore | skill_index |")
        doc.w("|---|---:|---:|---:|---:|---:|")
        total_b = sum(t['n_b'] for t in per_tier.values()
                      if t and t.get('n_b') is not None)
        for tier_label in ['Premium', 'High', 'Mid', 'Low', 'Micro']:
            t = per_tier.get(tier_label)
            if not t: continue
            vol_pct = t['n_b'] / total_b * 100 if total_b else 0
            doc.w(f"| {tier_label} | {t['n_t']} | {t['n_b']} | "
                  f"{vol_pct:.0f}% | {t['fin_score']:.1f}% | {t['skill_index']} |")
        if today:
            doc.w(f"| **TODAY weighted** | **{today['n_t']}** | **{today['n_b']}** | "
                  f"100% | **{today['fin_score']:.1f}%** | **{today['skill_index']}** |")
        doc.w("")
    doc.w("</details>")
    doc.w("")


def _emit_section_i(doc, s, rd, hands):
    eai_summary = _eai_one_liner(s)
    doc.section("sec-1", "S1. Reality Check (Variance vs Skill)", eai_summary)

    # I.1 Per-Tournament P&L
    # Ron 2026-05-31: show ALL tournaments (removed 20 cap — sessions rarely
    # have more than 40). Sort by |net_bb| descending so biggest wins AND
    # biggest losses both appear at the top (most impactful first).
    pnl = s['_per_tourney_pnl']
    # Sort by |net_bb| descending (biggest impact first). Cap at 50 for
    # large sessions (10K+ hands can have 100+ tournaments — show a note).
    # Sort by hands played (deep runs first, early bustouts last)
    pnl_sorted = sorted(pnl, key=lambda t: -t.get('hands', 0))
    _pnl_total = len(pnl_sorted)
    if _pnl_total > 50:
        pnl_sorted = pnl_sorted[:50]
    _cap_note = f" (top 50 of {_pnl_total} by impact)" if _pnl_total > 50 else ""
    summary = _per_tourney_one_liner(pnl_sorted) + f" — {_pnl_total} tournaments{_cap_note}"
    doc.subsection("sec-1-1", "S1.1 Per-Tournament P&L", summary)
    # B150 (Ron 2026-05-23): when the USD overlay is present, add $Net + ROI
    # columns so the per-tournament financial reality sits beside the BB/100
    # decision-quality numbers (memory: show both side by side).
    _usd_pt = (rd.get('usd_overlay', {}) or {}).get('per_tournament') or []
    _usd_by_name = {}
    _usd_by_tid = {}
    for u in _usd_pt:
        un = (u.get('name') or '').strip()
        if un:
            _usd_by_name[un] = u
        # B228 (Ron 2026-05-25): index by tournament id — the robust key.
        _tid = str(u.get('tid', '') or '')
        if _tid:
            _usd_by_tid[_tid] = u

    def _usd_match(tname, tid=None):
        # B228: prefer the tournament_id join — GG summary names carry ": $"
        # punctuation the HH names lack, so the old [:20] substring match
        # silently failed and every $Net/ROI cell rendered "—".
        _t = str(tid or '')
        if _t and _t in _usd_by_tid:
            return _usd_by_tid[_t]
        tname = (tname or '').strip()
        if tname in _usd_by_name:
            return _usd_by_name[tname]
        for un, u in _usd_by_name.items():
            if tname[:20] and (tname[:20] in un or un[:20] in tname):
                return u
        return None

    # Phase 2: §3 tournament_pnl grammar — typed block, standardised columns.
    # Ron 2026-05-31: added Cash$ column (total cash received incl bounties,
    # helpful where big bounties but no ITM) + total row.
    # B-V10 FEATURE (2026-06-01): per-tournament narrative ("lost flip",
    # "card dead", "busted as 65% favorite", etc.)
    _eai_hands_raw = (s.get('eai') or {}).get('hands') or []
    from gem_report_draft.sections_xiv import _tourney_narrative
    _narratives = _tourney_narrative(hands, _eai_hands_raw,
                                     buyin_breakdown=rd.get('buyin_breakdown'))
    _have_usd = bool(_usd_by_name or _usd_by_tid)
    if _have_usd:
        _tp_hdr = "| Date | Tournament | Bullets | Hands | BI | $net | %ROI | NetBB | bb/100 | Why |"
        _tp_sep = "|---|---|---|---|---|---|---|---|---|---|"
    else:
        _tp_hdr = "| Date | Tournament | Bullets | Hands | BI | NetBB | bb/100 | Why |"
        _tp_sep = "|---|---|---|---|---|---|---|---|"
    _tp_rows = []
    # Accumulators for total row
    _tot_bullets = 0; _tot_hands = 0; _tot_bi = 0.0
    _tot_cash = 0.0; _tot_net_usd = 0.0; _tot_cost = 0.0
    _tot_net_bb = 0.0
    _prev_date = None  # for group/merge date column
    for t in pnl_sorted:
        name = _short_tournament(t['tournament'])
        _tot_bullets += t.get('bullets', 0)
        _tot_hands += t.get('hands', 0)
        _tot_net_bb += t.get('net_bb', 0)
        if _have_usd:
            u = _usd_match(t['tournament'], t.get('tournament_id'))
            if u and u.get('cost'):
                _ucost = u.get('cost', 0)
                _ucash = u.get('cash_total', 0)
                _unet = _ucash - _ucost
                _uroi = (_unet / _ucost * 100) if _ucost else 0
                _ue = '🟢' if _unet > 0 else ('🟡' if _unet == 0 else '🔴')
                _bi_cell = _fmt_usd(_ucost)
                _net_cell = f"{_ue} {_fmt_usd(_unet, plus=True)}"
                _roi_cell = f"{_uroi:+.0f}%"
                _tot_cost += _ucost
                _tot_cash += _ucash
                _tot_net_usd += _unet
            else:
                _pbi = t.get('buyin', 0) * t.get('bullets', 1)
                _bi_cell = _fmt_usd(_pbi) if _pbi else "—"
                _net_cell = "—"
                _roi_cell = "—"
                _tot_cost += _pbi
            _why = _narratives.get(t['tournament'], '')
            _tp_rows.append(
                f"| {t['date'] if t['date'] != _prev_date else ''} | {name} | {t['bullets']} | {t['hands']} | "
                f"{_bi_cell} | {_net_cell} | {_roi_cell} | "
                f"{t['net_bb']:+.1f} | {t['bb_per_100']:+.1f} | {_why} |")
            _prev_date = t['date']
        else:
            _pbi = t.get('buyin', 0) * t.get('bullets', 1)
            _tot_bi += _pbi
            _why = _narratives.get(t['tournament'], '')
            _tp_rows.append(
                f"| {t['date'] if t['date'] != _prev_date else ''} | {name} | {t['bullets']} | {t['hands']} | "
                f"{_fmt_usd(_pbi)} | {t['net_bb']:+.1f} | {t['bb_per_100']:+.1f} | {_why} |")
            _prev_date = t['date']
    # Total row — BI uses the per-row blend (USD cost where settled, filename
    # buyin where running). Cash/Net/ROI use settled-only (running tournaments
    # have no finish data). B-V10 (2026-06-01): _tot_cost is the correct blend;
    # _usd_totals['total_cost'] is settled-only and understates when tournaments
    # are still running.
    _usd_totals = (rd.get('usd_overlay', {}) or {}).get('totals', {}) or {}
    _tot_bb100 = (_tot_net_bb / _tot_hands * 100) if _tot_hands else 0
    if _have_usd:
        # Ron decision (2026-06-01): Total = actual money in. When the USD
        # overlay knows about re-entries the HH files don't cover, use the
        # overlay's higher total. For running tournaments, add filename cost.
        _overlay_cost = _usd_totals.get('total_cost', 0)
        _final_cost = max(_tot_cost, _overlay_cost)  # actual money in
        _final_cash = _usd_totals.get('total_cash', _tot_cash)
        _final_net = _usd_totals.get('total_net', _tot_net_usd)
        # ROI on settled basis only (running tournaments have unknown outcome)
        _settled_cost = _usd_totals.get('total_cost', _tot_cost)
        _final_roi = (_final_net / _settled_cost * 100) if _settled_cost else 0
        _tot_e = '🟢' if _final_net > 0 else ('🟡' if _final_net == 0 else '🔴')
        # Count running tournaments for the note
        _n_running = sum(1 for t in pnl_sorted
                         if _have_usd and not _usd_match(t['tournament'], t.get('tournament_id')))
        _running_cost = sum(t.get('buyin', 0) * t.get('bullets', 1)
                            for t in pnl_sorted
                            if _have_usd and not _usd_match(t['tournament'], t.get('tournament_id')))
        _tp_rows.append(
            f"| | **Total** | **{_tot_bullets}** | **{_tot_hands}** | "
            f"**{_fmt_usd(_final_cost)}** | "
            f"**{_tot_e} {_fmt_usd(_final_net, plus=True)}** | **{_final_roi:+.0f}%** | "
            f"**{_tot_net_bb:+.1f}** | **{_tot_bb100:+.1f}** | |")
        if _n_running > 0:
            _tp_rows.append(
                f"| | *{_n_running} tournament(s) still running "
                f"({_fmt_usd(_running_cost)} invested) — $net/%ROI "
                f"reflect settled results only* | | | | | | | | |")
    else:
        _tp_rows.append(
            f"| | **Total** | **{_tot_bullets}** | **{_tot_hands}** | "
            f"**{_fmt_usd(_tot_bi)}** | **{_tot_net_bb:+.1f}** | **{_tot_bb100:+.1f}** | |")
    _tp_blk = financial_table_block("per-tourney-pnl", "tournament_pnl",
                                    _tp_hdr, _tp_sep, _tp_rows)
    doc.write_block(_tp_blk)
    doc.w("")

    # Phase 4.8: Deep Runs — moved here from sec-1-2 per user review.
    _emit_deep_runs(doc, s, hands)

    # WIRING: Stack trajectories per tournament
    _trajectories = s.get('stack_trajectories', {})
    if _trajectories:
        doc.w(f"<details><summary><strong>Stack trajectories</strong>{_new_badge('stack_trajectory')} "
              f"({len(_trajectories)} tournaments)</summary>")
        doc.w("")
        _hbi_traj = {h.get('id'): h for h in hands}
        for tid, traj in sorted(_trajectories.items(),
                                 key=lambda x: -x[1].get('n_hands', 0))[:8]:
            _tname = next((h.get('tournament', tid) for h in hands
                          if (h.get('tournament_id') or h.get('tournament', '')) == tid), tid)
            _tshort = _tname[:40] + '...' if len(_tname) > 40 else _tname
            # B-V14: escape markdown-significant [] in tournament names —
            # they get interpreted as link syntax and mangle hand-ref anchors
            _tshort = _tshort.replace('[', '\\[').replace(']', '\\]')
            _peak_h = _hbi_traj.get(traj.get('peak_hand'))
            _valley_h = _hbi_traj.get(traj.get('valley_hand'))
            # v8.4.0: compact trajectory — just hand ID pill + BB, no tournament name
            _peak_id = _hand_ref_id_only(_peak_h) if _peak_h else '?'
            _valley_id = _hand_ref_id_only(_valley_h) if _valley_h else '?'
            _peak_bb = traj.get('peak_bb', 0)
            _valley_bb = traj.get('valley_bb', 0)
            _start = traj['start_bb']
            _end = traj['end_bb']
            _net_traj = _end - _start
            _net_cls = 'hand-net-pos' if _net_traj > 0 else ('hand-net-neg' if _net_traj < 0 else 'hand-net-neu')
            _net_pill = f'<span class="{_net_cls}">{_net_traj:+.0f}BB</span>'
            doc.w(f"**{_tshort}** ({traj['n_hands']}h): "
                  f"{_start:.0f} → "
                  f"peak **{_peak_bb:.0f}BB** {_peak_id} → "
                  f"low **{_valley_bb:.0f}BB** {_valley_id} → "
                  f"{_end:.0f}BB {_net_pill}")
            doc.w("")
        doc.w("</details>")
        doc.w("")

    # Phase 4.8: Full Result Attribution — moved here from TL;DR <details>.
    # Lazy import to avoid circular dependency (tldr imports from _helpers/_html,
    # sections_financial also imports from _helpers/_html — but neither imports
    # the other at module level).
    from gem_report_draft.tldr import _emit_results_attribution
    _emit_results_attribution(doc, s, rd)

    # I.4 All-Ins (renamed from EAI per user review, Phase 4.8)
    eai = s.get('eai', {})
    eai_adj = s.get('eai_ev_adjusted', {})
    # Build dynamic header: "All-Ins [dot] [delta wins] [Delta BB]"
    _ai_delta_wins = 0
    for _adj_k in ('preflop', 'postflop'):
        _adj_d = (eai_adj or {}).get(_adj_k, {})
        _ai_delta_wins += _adj_d.get('delta_wins', 0)
    _ai_bb_var = ((eai_adj or {}).get('approx_bb_variance_pf', 0)
                  + (eai_adj or {}).get('approx_bb_variance_post', 0))
    _ai_dot = "\U0001f534" if _ai_delta_wins < -1.5 else ("\U0001f7e2" if _ai_delta_wins >= 0 else "\U0001f7e1")
    _ai_summary = (f"{_ai_dot} {_ai_delta_wins:+.1f} delta wins, "
                   f"{_ai_bb_var:+.1f} BB" if eai_adj
                   else f"{eai.get('total',0)} all-in spots")
    doc.subsection("sec-1-4", "S1.4 All-Ins", _ai_summary)
    pf = eai.get('preflop', {})
    post = eai.get('postflop', {})

    # Phase 4.8: merged preflop + postflop into one table with grouped Street.
    # Column order: Street (grouped), Status, Category, Actual, Expected, Delta, Won, Count
    _N_hands = len(hands) or 1
    _pname = (rd.get('player_name', '') or s.get('volume', {}).get('player_name', '') or '').lower()
    _is_ron = _pname in ('ron', 'knockman')
    _cev_hdr = ' | cEV/100 |' if _is_ron else ' |'
    # v8.7.8 FIX (E5): separator must have same column count as header.
    # When _is_ron adds cEV/100, both header AND separator need the extra column.
    _cev_sep = '|---|' if _is_ron else '|'
    _vl_hdr = f"| Street | Status | Category | Actual | Expected | Delta | Won | Count | BB/100{_cev_hdr}"
    _vl_sep = f"|---|:---:|---|---|---|---|---|---|---{_cev_sep}"
    _vl_all_rows = []

    # B-V10: quality check computation — hoisted before the table so
    # _ai_rows can highlight "Behind" rows when the QC is bad.
    _eai_hands_qc = (eai.get('hands') or [])
    _hands_by_id_qc = {h.get('id'): h for h in hands if h.get('id')}
    _cooler_ids_qc = set()
    for _ck in ((s.get('coolers') or {}).get('hands') or []):
        _cid = _ck.get('id') if isinstance(_ck, dict) else (_ck if isinstance(_ck, str) else None)
        if _cid:
            _cooler_ids_qc.add(_cid)
    _behind_total = 0; _behind_coolers = 0; _behind_bounty_ok = 0; _behind_avoidable = 0
    _BEHIND_CUT = 0.42; _BOUNTY_DISCOUNT = 0.08
    for e in _eai_hands_qc:
        eq = e.get('hero_equity')
        if eq is None: continue
        if eq > 1.5: eq = eq / 100.0
        if eq >= _BEHIND_CUT: continue
        _behind_total += 1
        _eid = e.get('id', '')
        if _eid in _cooler_ids_qc:
            _behind_coolers += 1
        else:
            _h_qc = _hands_by_id_qc.get(_eid, {})
            _fmt_qc = (_h_qc.get('format') or '').upper()
            _is_bounty = _fmt_qc in ('BOUNTY', 'PKO', 'MYSTERY_BOUNTY')
            if _is_bounty and eq >= (_BEHIND_CUT - _BOUNTY_DISCOUNT):
                _behind_bounty_ok += 1
            else:
                _behind_avoidable += 1
    _total_ai = len(_eai_hands_qc)

    # Collect hand IDs per street × category for drill-down popups
    from collections import defaultdict as _ddict_ai
    _ai_ids = _ddict_ai(lambda: _ddict_ai(list))  # [street][category] → [ids]
    for _be in _eai_hands_qc:
        _beq = _be.get('hero_equity')
        if _beq is None or not _be.get('id'):
            continue
        _beq_n = _beq * 100.0 if _beq <= 1.5 else _beq
        _bst = _be.get('street', 'preflop')
        _bkey = 'preflop' if _bst == 'preflop' else 'postflop'
        _cat = _be.get('category', 'flip')          # v8.8.9 BUG-1: use analyzer's hand-rank classification
        _ai_ids[_bkey][_cat].append(_be['id'])
    _behind_ids_by_street = {k: _ai_ids[k].get('behind', []) for k in ('preflop', 'postflop')}

    def _ai_rows(street_label, street_data, expectations):
        rows = []
        first = True
        for cat, exp_pct, exp_str in expectations:
            d = street_data.get(cat, {})
            actual = d.get('pct', 0)
            n = d.get('count', 0)
            rel = (actual / exp_pct - 1.0) * 100.0 if exp_pct else 0.0
            if n < 3:
                status = "⚪"
            elif abs(rel) < 15:
                status = "\U0001f7e2"
            elif abs(rel) < 30:
                status = "\U0001f7e1"
            else:
                status = "\U0001f534"
            # Phase 4.8 v3: grouped Street — show label on first row only
            street_cell = street_label if first else ""
            first = False
            # B-V10: ALL category counts are hand-list popups
            _cat_cell = cat.title()
            _st_key = street_label.lower()
            _cat_ids = _ai_ids.get(_st_key, {}).get(cat, [])[:30]
            if _cat_ids and n > 0:
                _cat_str = ','.join(_cat_ids)
                _count_cell = (f'<a class="hand-list-trigger" href="#" '
                               f'data-hids="{_cat_str}" '
                               f'data-list-title="{street_label} {cat.title()} All-Ins ({n})">'
                               f'{n}</a>')
            else:
                _count_cell = str(n)
            # Red highlight the Behind label when quality check is bad
            if cat == 'behind' and n > 0 and _behind_avoidable >= 3:
                _cat_cell = f'**🔴 {cat.title()}**'
            # BB/100: sum net_bb for ALL hands in this category (not capped popup list)
            _all_cat_ids = _ai_ids.get(_st_key, {}).get(cat, [])
            _bb_impact = sum((_hands_by_id_qc.get(hid) or {}).get('net_bb', 0)
                            for hid in _all_cat_ids)
            _bb100 = (_bb_impact / _N_hands * 100) if _N_hands else 0
            _bb_cls = 'net-pos' if _bb100 > 0 else 'net-neg' if _bb100 < 0 else ''
            _bb_str = f'<span class="{_bb_cls}">{_bb100:+.1f}</span>' if abs(_bb100) > 0.05 else '—'
            _cev_cell = ''
            if _is_ron and _bb_impact != 0:
                _avg_stack = sum((_hands_by_id_qc.get(hid) or {}).get('stack_bb', 0)
                                 for hid in _all_cat_ids) / max(len(_all_cat_ids), 1)
                _cev = (_bb_impact / max(_avg_stack, 1)) * 100 if _avg_stack > 0 else 0
                _cev_cls = 'net-pos' if _cev > 0 else 'net-neg' if _cev < 0 else ''
                _cev_cell = f' | <span class="{_cev_cls}">{_cev:+.1f}%</span>'
            elif _is_ron:
                _cev_cell = ' | —'
            rows.append(
                f"| {street_cell} | {status} | {_cat_cell} | "
                f"{actual:.1f}% | {exp_str} | {rel:+.0f}% | "
                f"{d.get('won','—')} | {_count_cell} | {_bb_str}{_cev_cell} |")
        # Total row from eai_ev_adjusted
        adj_key = street_label.lower()
        d = (eai_adj or {}).get(adj_key, {})
        if d:
            delta = d.get('delta_wins', 0)
            emoji = "\U0001f534" if delta < -1.5 else ("\U0001f7e1" if abs(delta) >= 1 else "\U0001f7e2")
            _st_bb = sum((_hands_by_id_qc.get(e.get('id')) or {}).get('net_bb', 0)
                         for e in _eai_hands_qc
                         if (e.get('street', 'preflop') == adj_key or
                             (adj_key == 'postflop' and e.get('street', '') != 'preflop')))
            _st_bb100 = (_st_bb / _N_hands * 100) if _N_hands else 0
            _st_bb_cls = 'net-pos' if _st_bb100 > 0 else 'net-neg' if _st_bb100 < 0 else ''
            _st_bb_str = f'<span class="{_st_bb_cls}">**{_st_bb100:+.1f}**</span>' if _st_bb_cls else f'**{_st_bb100:+.1f}**'
            _st_cev_cell = ''
            if _is_ron:
                _st_hand_ids = [e.get('id') for e in _eai_hands_qc
                                if (e.get('street', 'preflop') == adj_key or
                                    (adj_key == 'postflop' and e.get('street', '') != 'preflop'))]
                _st_avg_stk = (sum((_hands_by_id_qc.get(hid) or {}).get('stack_bb', 0)
                                   for hid in _st_hand_ids) / max(len(_st_hand_ids), 1)) if _st_hand_ids else 0
                if _st_avg_stk > 0 and _st_bb != 0:
                    _st_cev100 = (_st_bb / max(_st_avg_stk, 1)) * 100
                    _st_cev_cls = 'net-pos' if _st_cev100 > 0 else 'net-neg' if _st_cev100 < 0 else ''
                    _st_cev_cell = f' | <span class="{_st_cev_cls}">**{_st_cev100:+.1f}%**</span>'
                else:
                    _st_cev_cell = ' | —'
            rows.append(
                f"| | **{emoji}** | **Total** | "
                f"**{d.get('actual_win_pct',0):.1f}%** | "
                f"~{d.get('expected_win_pct',0):.1f}% | "
                f"**{delta:+.1f} wins** | "
                f"**{d.get('actual_wins',0):.1f}** | "
                f"**{d.get('total_spots',0)}** | {_st_bb_str}"
                + _st_cev_cell + ' |')
        return rows

    _vl_all_rows.extend(_ai_rows('Preflop', pf,
        [('ahead', 80, '~80%'), ('flip', 55, '~55%'), ('behind', 20, '~20%')]))
    _vl_all_rows.extend(_ai_rows('Postflop', post,
        [('ahead', 85, '~85%'), ('flip', 50, '~50%'), ('behind', 25, '~25%')]))
    # Grand total row — Phase 4.8 v3: "Total" not "Grand Total", include expected
    _gt = {}
    for _adj_k in ('preflop', 'postflop'):
        _d = (eai_adj or {}).get(_adj_k, {})
        for _f in ('total_spots', 'actual_wins', 'expected_wins', 'delta_wins'):
            _gt[_f] = _gt.get(_f, 0) + _d.get(_f, 0)
    if _gt.get('total_spots'):
        _gt_pct = 100.0 * _gt['actual_wins'] / _gt['total_spots'] if _gt['total_spots'] else 0
        _gt_exp = _gt.get('expected_wins', 0)
        _gt_exp_pct = 100.0 * _gt_exp / _gt['total_spots'] if _gt['total_spots'] and _gt_exp else 0
        _gt_exp_str = f"~{_gt_exp_pct:.1f}%" if _gt_exp else "—"
        _gt_emoji = "\U0001f534" if _gt['delta_wins'] < -1.5 else ("\U0001f7e1" if abs(_gt['delta_wins']) >= 1 else "\U0001f7e2")
        _gt_bb = sum((_hands_by_id_qc.get(e.get('id')) or {}).get('net_bb', 0)
                     for e in _eai_hands_qc)
        _gt_bb100 = (_gt_bb / _N_hands * 100) if _N_hands else 0
        _gt_bb_cls = 'net-pos' if _gt_bb100 > 0 else 'net-neg' if _gt_bb100 < 0 else ''
        _gt_bb_str = f'<span class="{_gt_bb_cls}">**{_gt_bb100:+.1f}**</span>' if _gt_bb_cls else f'**{_gt_bb100:+.1f}**'
        # cEV/100 for grand total (Ron column) — same formula as per-category
        _gt_cev_cell = ''
        if _is_ron:
            _gt_all_ids = [e.get('id') for e in _eai_hands_qc]
            _gt_avg_stk = (sum((_hands_by_id_qc.get(hid) or {}).get('stack_bb', 0)
                               for hid in _gt_all_ids) / max(len(_gt_all_ids), 1))
            if _gt_avg_stk > 0 and _gt_bb != 0:
                _gt_cev100 = (_gt_bb / max(_gt_avg_stk, 1)) * 100
                _gt_cev_cls = 'net-pos' if _gt_cev100 > 0 else 'net-neg' if _gt_cev100 < 0 else ''
                _gt_cev_cell = f' | <span class="{_gt_cev_cls}">**{_gt_cev100:+.1f}%**</span>'
            else:
                _gt_cev_cell = ' | —'
        _vl_all_rows.append(
            f"| **All** | **{_gt_emoji}** | **Total** | "
            f"**{_gt_pct:.1f}%** | {_gt_exp_str} | "
            f"**{_gt['delta_wins']:+.1f} wins** | "
            f"**{_gt['actual_wins']:.1f}** | "
            f"**{_gt['total_spots']}** | {_gt_bb_str}"
            + _gt_cev_cell + ' |')
    _vl_blk = variance_ledger_block("eai-all", _vl_hdr, _vl_sep, _vl_all_rows)
    doc.write_block(_vl_blk)
    doc.w("")

    # QC display (computation already done above before the table)
    if _total_ai >= 10 and _behind_total > 0:
        _avoid_pct = 100.0 * _behind_avoidable / _total_ai if _total_ai else 0
        _behind_pct = 100.0 * _behind_total / _total_ai if _total_ai else 0
        if _behind_avoidable >= 3 and _avoid_pct > 15:
            _qc_emoji = '\U0001f534'
            _qc_label = 'getting it in light'
        elif _behind_avoidable >= 2:
            _qc_emoji = '\U0001f7e1'
            _qc_label = 'borderline'
        else:
            _qc_emoji = '\U0001f7e2'
            _qc_label = 'clean'
        _parts = [f"{_behind_total} behind all-ins"]
        _sub_parts = []
        if _behind_coolers:
            _sub_parts.append(f"{_behind_coolers} coolers")
        if _behind_bounty_ok:
            _sub_parts.append(f"{_behind_bounty_ok} bounty-justified")
        if _sub_parts:
            _parts.append(f"− {' − '.join(_sub_parts)}")
        _parts.append(f"= **{_behind_avoidable} avoidable**")
        doc.w(f"> {_qc_emoji} **Quality check:** {' '.join(_parts)} "
              f"({_avoid_pct:.0f}% of {_total_ai} all-ins). "
              f"{'Behind rate ' + f'{_behind_pct:.0f}% vs population ~25% — ' if _behind_pct > 30 else ''}"
              f"{_qc_label}.")
        doc.w("")

    # I.4 suckout ledger (B238/B244). Phase 4.8: merged into one table with
    # "Direction" first column (Sucked out / Hero sucked out), text -> tooltip.
    _sk = s.get('suckouts', {}) or {}
    _sk_against = _sk.get('against_hero', []) or []
    _sk_by = _sk.get('by_hero', []) or []
    if _sk_against or _sk_by:
        doc.w("")
        doc.w(f'<span data-tip="All-ins where the equity favourite did not win '
              f'— Hero a ≥60% favourite who lost (against Hero) or a ≤40% '
              f'underdog who won (by Hero). Equity is the true multiway '
              f'all-in number at the moment of the all-in. Variance, not '
              f'leaks — separated here so they are not confused with the '
              f'structural coolers.">'
              f'<strong>\U0001f922 Suckout ledger</strong> — {len(_sk_against)} against Hero · '
              f'{len(_sk_by)} by Hero</span>')
        doc.w("")
        doc.w("| Hand | Hero | Villain(s) | Board | Hero eq | Street |")
        doc.w("|---|---|---|---|---|---|")
        # Renderer link BUG-4: use _hand_ref so citations are registered
        _sk_by_id = {h.get('id', ''): h for h in hands}
        for direction, rows in [("\U0001f922 Sucked out (Hero was favourite, lost)",
                                 _sk_against),
                                ("\U0001f340 Hero sucked out (Hero was underdog, won)",
                                 _sk_by)]:
            if not rows:
                continue
            # Group header instead of per-row Direction column
            doc.w(f"| **{direction} ({len(rows)})** | | | | | |")
            for e in sorted(rows, key=lambda x: -(x.get('hero_equity') or 0)):
                _eid = e.get('id', '')
                _full = _sk_by_id.get(_eid, e)
                # Build a minimal hand dict for _hand_ref if full not found
                if _full is e and not _full.get('tournament'):
                    _full = dict(e)
                    _full.setdefault('tournament', e.get('tournament', ''))
                    _full.setdefault('date', e.get('date', ''))
                _ref = _hand_ref(_full)
                # V25.3 item 7a: add queue group attribute for scoped navigation
                _slug = 'suckout-fav-lost' if '\U0001f922' in direction else 'suckout-underdog-won'
                _ref = _ref.replace(
                    'class="hand-ref xref"',
                    f'class="hand-ref xref" data-hand-queue-group="{_slug}" '
                    f'data-hand-queue-title="Suckout ledger — {direction}"')
                _vil = ' / '.join(_cards_str_to_pills(v)
                                  for v in (e.get('villains_all')
                                            or [e.get('villain', '')]))
                _eq = e.get('hero_equity')
                _eq_s = f"{_eq*100:.0f}%" if _eq is not None else "—"
                doc.w(f"| {_ref} | "
                      f"{_cards_str_to_pills(e.get('hero','—'))} "
                      f"| {_vil} | {_cards_str_to_pills(e.get('board','—'))} "
                      f"| {_eq_s} | {e.get('street','—')} |")
        doc.w("")

    # I.5 Card Quality
    # B157 (Ron 2026-05-23): rebuilt to use the same CI + run-marker
    # architecture as I.6. The old code fired 🟢/🟡/🔴 off a flat ±tolerance
    # threshold with no sample-size awareness — which reads as a "leak"
    # verdict when card quality is pure deal variance (no skill component).
    # New logic: Wilson 90% CI on the dealt rate (n = total hands); fire
    # 🔥 (ran hot, more than expected) / 🥶 (ran cold) ONLY when the model
    # expectation falls OUTSIDE the CI — otherwise 🟢 (statistically as
    # dealt). The header carries the composite (Prem+Strong) marker.
    cq = s.get('card_quality', {})
    n_cq = s.get('volume', {}).get('hands', 0) or 0
    prem_pct = cq.get('premiums_pct', 0)
    _cq_rows = [
        ('Premiums', prem_pct, 3.0, cq.get('premiums')),
        ('Strong', cq.get('strong_pct', 0), 4.0, cq.get('strong')),
        ('Prem+Strong', cq.get('prem_strong_pct', 0), 5.7, None),
        ('Suited', cq.get('suited_pct', 0), 23.5, None),
        ('Pairs', cq.get('pair_pct', 0), 5.9, None),
        ('Aces', cq.get('ace_pct', 0), 14.9, None),
    ]
    _cq_built = []
    _cq_header_marker = ''
    for name, val, expected, cnt in _cq_rows:
        if cnt is None:
            cnt = round(val / 100.0 * n_cq) if n_cq else 0
        if n_cq:
            ci_lo, ci_hi = _wilson_ci(cnt, n_cq)
        else:
            ci_lo, ci_hi = 0.0, 0.0
        # B182 (Ron review 2026-05-25): delta is relative — (Session/Expected
        # - 1) in % — matching the I.6 Made-Hands "%Δ vs exp" convention
        # (B180). Absolute pp subtraction understated how cold/hot a run was
        # (e.g. premiums 2.1 vs 3.0 reads -0.9pp but is a -30% shortfall).
        delta = ((val / expected - 1.0) * 100.0) if expected else 0.0
        if n_cq and expected < ci_lo:
            marker = '🔥'  # dealt more than expected — ran hot
        elif n_cq and expected > ci_hi:
            marker = '🥶'  # dealt fewer than expected — ran cold
        else:
            marker = '🟢'  # expectation inside CI — statistically as dealt
        if name == 'Prem+Strong':
            _cq_header_marker = '' if marker == '🟢' else f" {marker}"
        _cq_built.append((name, val, expected, delta, ci_lo, ci_hi, marker))
    # B223 (Ron review 2026-05-25): a single "Good Hands" total row — the
    # overall feel of how often Hero was dealt cards worth getting. The other
    # rows overlap, so this is the non-overlapping union (premium ∪ strong ∪
    # any pocket pair), counted once per hand. Header carries it concisely.
    _good_pct = cq.get('good_hands_pct', 0)
    _good_n = cq.get('good_hands', 0)
    _good_exp = cq.get('good_hands_expected', 11.5)
    if n_cq:
        _good_ci_lo, _good_ci_hi = _wilson_ci(_good_n, n_cq)
    else:
        _good_ci_lo, _good_ci_hi = 0.0, 0.0
    _good_delta = ((_good_pct / _good_exp - 1.0) * 100.0) if _good_exp else 0.0
    if n_cq and _good_exp < _good_ci_lo:
        _good_marker = '🔥'
    elif n_cq and _good_exp > _good_ci_hi:
        _good_marker = '🥶'
    else:
        _good_marker = '🟢'
    doc.subsection("sec-1-5", "S1.5 Card Quality" + _cq_header_marker,
                   f"good hands {_good_pct:.1f}% vs ~{_good_exp:.1f}% expected "
                   f"{_good_marker}")
    # Phase 4.8: descriptive text moved to data-tip on header area
    doc.w('<span data-tip="Card quality is pure deal variance — there is no '
          'skill component, so 🟢 means the deal was statistically as-expected '
          '(model rate inside Hero\'s 90% CI), not that anything was done well. '
          '🔥/🥶 fire only when the run was genuinely hot/cold at this sample. '
          'Header marker tracks the Prem+Strong composite."></span>')
    doc.w("")
    doc.w("| Metric | Session (n) | Expected | %Δ vs exp | CI 90% | Status |")
    doc.w("|---|---|---|---|---|---|")
    for name, val, expected, delta, ci_lo, ci_hi, marker in _cq_built:
        doc.w(f"| {name} | {val:.1f}% (n={n_cq}) | {expected:.1f}% | "
              f"{delta:+.0f}% | {ci_lo:.0f}-{ci_hi:.0f}% | {marker} |")
    # B-V10: add "Non-premium pairs (22-TT)" row so the user sees WHY
    # the Good Hands total can be negative despite premiums running hot.
    # Non-premium pairs = all pairs minus premium pairs (JJ, QQ, KK, AA)
    # minus strong pairs (TT, 99) = 22-88 (7 classes × 6 combos = 42/1326 ≈ 3.2%)
    _NON_PREM_PAIR_EXP = 3.2  # 22-88 expected ~3.2% of deals
    _pair_pct = cq.get('pair_pct', 0)
    from gem_analyzer import normalize_hand as _nh, PREMIUMS as _PREM, STRONG as _STR
    _prem_pair_pct = sum(1 for h in hands
                         if len(h.get('cards',[])) >= 2
                         and h['cards'][0][0] == h['cards'][1][0]
                         and _nh(h.get('cards',[])) in (_PREM | _STR)) / max(n_cq, 1) * 100
    _np_pair_pct = _pair_pct - _prem_pair_pct
    _np_pair_delta = ((_np_pair_pct / _NON_PREM_PAIR_EXP - 1.0) * 100.0) if _NON_PREM_PAIR_EXP else 0
    _np_pair_n = round(_np_pair_pct * n_cq / 100)
    _np_ci = _wilson_ci(_np_pair_n, n_cq) if n_cq else (0, 0)
    _np_marker = '🥶' if _np_pair_delta < -15 else ('🔥' if _np_pair_delta > 15 else '🟢')
    doc.w(f'| <span data-tip="22-88 pocket pairs (excludes premium/strong pairs JJ+ and TT/99)">'
          f'Non-prem pairs (22-88)</span> | '
          f'{_np_pair_pct:.1f}% (n={n_cq}) | {_NON_PREM_PAIR_EXP:.1f}% | '
          f'{_np_pair_delta:+.0f}% | {_np_ci[0]:.0f}-{_np_ci[1]:.0f}% | {_np_marker} |')
    # Good Hands total
    _good_tip = ("Non-overlapping union: premium, strong, or any pocket pair, "
                 "counted once per hand (the rows above overlap: AA is a premium "
                 "AND a pair). Suited and Aces excluded — weak suited and offsuit "
                 "weak-ace hands are not 'good' cards.")
    doc.w(f'| <span data-tip="{_good_tip}">**Good Hands (total)**</span> | '
          f'**{_good_pct:.1f}% (n={n_cq})** | '
          f'~{_good_exp:.1f}% | **{_good_delta:+.0f}%** | '
          f'{_good_ci_lo:.0f}-{_good_ci_hi:.0f}% | **{_good_marker}** |')
    doc.w("")
    # Phase 4.8: card quality description moved to tooltip on subsection header.
    # (was two italicized paragraphs of explanatory text)

    # I.6 Made Hands vs Expected (NEW)
    # v7.36: gate color signal at n>=30 (per B20). At smaller samples the CI
    # is too wide for the target band to mean anything — show the rate but
    # don't fire 🟢/🟡/🔴 verdicts that read as deterministic when they're noise.
    mh_data = s['_made_hands']
    # E1 (Ron 2026-05-11): summarize where Hero made above/below expectation
    # so the section header tells the story at a glance.
    MH_NMIN = 30
    deltas = []
    _mh_hot = _mh_cold = 0  # B147b (Ron 2026-05-23): net run-marker tally
    for cls in ['set', 'flush', 'straight', 'two_pair', 'full_house']:
        d = mh_data[cls]
        opp = d.get('opp', 0)
        if opp >= MH_NMIN:
            made = d['made']
            expected_n = d['expected'] * opp / 100.0
            delta_n = made - expected_n
            if abs(delta_n) >= 1.5:  # only mention deltas >=1.5 hands
                deltas.append((cls, delta_n))
            # CI-based significance: model expectation outside Hero's 90% CI
            _exp = d.get('expected')
            _ci = d.get('ci') or (None, None)
            if _exp is not None and _ci[0] is not None and _ci[1] is not None:
                if _exp < _ci[0]:
                    _mh_hot += 1
                elif _exp > _ci[1]:
                    _mh_cold += 1
    summary_parts = []
    deltas.sort(key=lambda x: abs(x[1]), reverse=True)
    for cls, delta in deltas[:3]:
        sign = '+' if delta > 0 else ''
        summary_parts.append(f"{sign}{delta:.0f} on {cls.replace('_',' ')}s")
    summary_line = ', '.join(summary_parts) if summary_parts else 'all classes near expectation'
    # Header run-marker: net direction of statistically-significant classes.
    if _mh_cold > _mh_hot:
        _mh_header = ' 🥶'
    elif _mh_hot > _mh_cold:
        _mh_header = ' 🔥'
    else:
        _mh_header = ''
    doc.subsection("sec-1-6", "S1.6 Made Hands vs Expected" + _mh_header,
                   f"what Hero actually made vs expectation — {summary_line}")
    # Phase 4.8: column reorder per user review. "How to read" text → tooltips.
    doc.w(f'| Class '
          f'| <span data-tip="Gated at n≥{MH_NMIN} — below that the CI is too wide to '
          f'mean anything, so rate shown for transparency with no colour signal.">Status</span> '
          f'| <span data-tip="🔥 ran above expectation, 🥶 below, — = as expected. '
          f'Fires only when expectation falls outside Hero\'s 90% CI. Distinct from Status, '
          f'which judges whether the rate itself is in a healthy band.">Luck</span> '
          f'| Rate | CI 90% '
          f'| <span data-tip="Rough population baselines, calibrated against typical '
          f'online-MTT pool data.">Expected~</span> '
          f'| <span data-tip="Relative difference (observed / expected - 1). Read alongside '
          f'the CI: a delta the CI does not span is the real signal.">%Δ vs exp</span> '
          f'| <span data-tip="Two-pair and full-house denominators are fuzzier (~) — the '
          f'opportunity definition there is approximate.">Opp Denom</span> '
          f'| <span data-tip="Flop-archetype mix when Hero made the class — useful for EV '
          f'interpretation (e.g. two pair on paired board = bluff-catcher, sets on monotone '
          f'= flush redraws).">Board textures</span> |')
    doc.w("|---|:---:|:---:|---|---|---|---|---|---|")
    for cls in ['set', 'flush', 'straight', 'two_pair', 'full_house']:
        d = mh_data[cls]
        ci_lo, ci_hi = d['ci']
        target_lo, target_hi = d['target']
        opp = d.get('opp', 0)
        verdict = d['verdict'] if opp >= MH_NMIN else f"⚪ (n={opp}&lt;{MH_NMIN})"
        # B203 (Ron review 2026-05-25): the run-hot/cold marker was appended to
        # the Status cell ("🔴 🔥"), which wrapped to two lines in the HTML —
        # Ron: "Status should be one row, not emoji over emoji". Split it into
        # its own Luck column so each cell carries exactly one emoji.
        luck = '—'
        if opp >= MH_NMIN:
            _exp = d.get('expected')
            if _exp is not None and ci_lo is not None and ci_hi is not None:
                if _exp < ci_lo:
                    luck = '🔥'
                elif _exp > ci_hi:
                    luck = '🥶'
        # B65 (v7.48, Ron 2026-05-12): board texture distribution when made.
        # Surfaces e.g. "2P made 4× — 3 on paired boards (bluffcatcher-quality
        # 2P), 1 on dry-low (real 2P)". Affects EV interpretation of the rate.
        tdist = d.get('texture_dist', {}) or {}
        if tdist:
            # Sort by count desc, take top 3, abbreviate archetype names
            sorted_arch = sorted(tdist.items(), key=lambda x: -x[1])
            parts = []
            for arch_id, cnt in sorted_arch[:3]:
                # Abbreviate common archetypes
                short = (arch_id.replace('_', ' ')
                                 .replace('paired ', 'pair-')
                                 .replace('coordinated', 'coord')
                                 .replace('disconnected', 'discon')
                                 .replace('connected', 'conn'))
                if len(short) > 18:
                    short = short[:16] + '…'
                parts.append(f"{short}×{cnt}")
            tdist_str = ', '.join(parts)
            if len(sorted_arch) > 3:
                tdist_str += f' (+{len(sorted_arch)-3})'
        else:
            tdist_str = '—'
        # B180 (Ron 2026-05-25): %Δ vs exp is a RELATIVE delta
        # (observed / expected - 1), not the absolute pp subtraction.
        # "made sets 28.6% vs 12% expected" reads as +138%, not +16.6pp.
        _exp_v = d.get('expected') or 0
        if _exp_v:
            _rel = (d['rate'] / _exp_v - 1.0) * 100.0
            _rel_cell = f"{_rel:+.0f}%"
        else:
            _rel_cell = "\u2014"
        # B215 (Ron review 2026-05-25): only the Board-textures column may
        # wrap — the rest (esp. the CI "22-36%") was breaking across two
        # lines. Pin every other cell with white-space:nowrap.
        def _nw(x):
            return f'<span style="white-space:nowrap">{x}</span>'
        _c_cls = cls.replace('_', ' ').title()
        _c_opp = f"{opp} ({d['opp_label']})"
        _c_rate = f"{d['rate']:.1f}%"
        _c_ci = f"{ci_lo:.0f}-{ci_hi:.0f}%"
        _c_exp = f"~{d['expected']:.0f}%"
        # Phase 4.8: reordered columns: Class, Status, Luck, Rate, CI, Expected, %Delta, Opp Denom, Board
        doc.w(f"| {_nw(_c_cls)} | {_nw(verdict)} | {_nw(luck)} | "
              f"{_nw(_c_rate)} | {_nw(_c_ci)} | {_nw(_c_exp)} | "
              f"{_nw(_rel_cell)} | {_nw(_c_opp)} | {tdist_str} |")
    # B-AVIEL FEATURE (2026-06-01): "Two Pair+" total row — aggregates all
    # premium made-hand classes so the user sees the combined run-hot/cold
    # signal at a glance ("I made 47 strong hands, expected 52").
    _tot_made = sum(mh_data[c]['made'] for c in ['set', 'flush', 'straight', 'two_pair', 'full_house'])
    _tot_opp = sum(mh_data[c].get('opp', 0) for c in ['set', 'flush', 'straight', 'two_pair', 'full_house'])
    _tot_exp_n = sum(mh_data[c]['expected'] * mh_data[c].get('opp', 0) / 100.0
                     for c in ['set', 'flush', 'straight', 'two_pair', 'full_house'])
    _tot_rate = (100.0 * _tot_made / _tot_opp) if _tot_opp else 0
    _tot_exp_pct = (100.0 * _tot_exp_n / _tot_opp) if _tot_opp else 0
    _tot_rel = ((_tot_rate / _tot_exp_pct - 1.0) * 100.0) if _tot_exp_pct else 0
    _tot_luck = '—'
    if _tot_opp >= MH_NMIN and _tot_exp_n > 0:
        # Simple z-test: (observed - expected) / sqrt(expected)
        import math
        _z = (_tot_made - _tot_exp_n) / math.sqrt(_tot_exp_n) if _tot_exp_n > 0 else 0
        if _z > 1.28:
            _tot_luck = '🔥'
        elif _z < -1.28:
            _tot_luck = '🥶'
    doc.w(f"| **Two Pair+** | — | {_tot_luck} | "
          f"**{_tot_rate:.1f}%** | — | "
          f"~{_tot_exp_pct:.0f}% | {_tot_rel:+.0f}% | "
          f"{_tot_made}/{_tot_opp} | — |")
    doc.w("")
    # Phase 4.8: "How to read" text moved to tooltips on column headers above.

    # I.7 Confirmed Coolers (TM5922982495 reclassified back here)
    coolers = s.get('coolers', {})
    cooler_hands = list(coolers.get('hands', []))  # copy for mutation
    # v7.43 (2026-05-09): symmetric analyst-override logic.
    #  (a) If analyst classified an auto-detected cooler as III.x
    #      (punt/read-dep/justified), drop it — analyst recognized agency.
    #  (b) If analyst classified a hand as I.7 that auto-detector missed
    #      (e.g. flush-over-flush postflop), add it — analyst caught a
    #      structural matchup the showdown-pattern detector didn't.
    analyst_pre = rd.get('analyst_commentary', {}) or {}
    analyst_iiix = {hid for hid, cmt in analyst_pre.items()
                    if isinstance(cmt, dict) and cmt.get('verdict', '').startswith(('III.0','III.1','III.2','III.4','III.5'))}
    analyst_i7 = {hid for hid, cmt in analyst_pre.items()
                  if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('I.7')}
    if analyst_iiix:
        cooler_hands = [c for c in cooler_hands if c.get('id') not in analyst_iiix]
    # Augment with analyst I.7 hands not already in the list
    existing_ids = {c.get('id') for c in cooler_hands}
    hands_by_id_full = {h.get('id', ''): h for h in hands}
    for hid in analyst_i7:
        if hid in existing_ids:
            continue
        h = hands_by_id_full.get(hid)
        if not h:
            continue
        cmt = analyst_pre.get(hid, {})
        # Build a synthetic cooler entry from the hand record + analyst spot
        spot = cmt.get('spot', '')
        hero_cards = ''.join(h.get('cards', []))
        board_list = h.get('board') or []
        board_str = ' '.join(board_list) if isinstance(board_list, list) else str(board_list)
        # B236 (Ron review 2026-05-26): an analyst-identified cooler previously
        # hardcoded villain='—'/street='—' because the synthetic entry had no
        # detector record to copy from. Pull the real villain hand from the
        # appendix showdown reveals ({pos:{cards,is_hero,outcome}}). For a
        # multiway all-in (e.g. QQ vs AA vs JJ) the cooler villain is the hand
        # that beat Hero — prefer the SD seat whose outcome=='won'; fall back
        # to joining every non-hero shown hand.
        villain_cards = '—'
        app_sd = (((rd.get('appendix_hand_details') or {}).get(hid, {}) or {})
                  .get('showdown', {}) or {})
        if app_sd:
            won_v, all_v = [], []
            for _info in app_sd.values():
                if _info.get('is_hero'):
                    continue
                _cards_l = _info.get('cards') or []
                # v8.12.4 (QA item 9): a voluntary one-card show by a folded
                # player ("shows [5s]") is not a matchup hand — skip it.
                if len(_cards_l) < 2 or _info.get('partial'):
                    continue
                _cs = ' '.join(_cards_l)
                all_v.append(_cs)
                if (_info.get('outcome') or '').startswith('won'):
                    won_v.append(_cs)
            if won_v:
                villain_cards = ' / '.join(won_v)
            elif all_v:
                villain_cards = ' / '.join(all_v)
        # Street: preflop-only lines all-in pre; else infer from all-in flags.
        if h.get('line_actions') == 'preflop_only' or h.get('pf_allin'):
            cooler_street = 'preflop'
        elif h.get('flop_allin'):
            cooler_street = 'flop'
        else:
            cooler_street = cmt.get('street') or '—'
        # Kind: prefer analyst spot text; else build a pair-over-pair label
        # when both hands are pocket pairs (matches the auto-detector format),
        # otherwise a street-aware generic.
        if spot:
            cooler_kind = spot[:60]
        else:
            _hr = (hero_cards[0:2], hero_cards[2:4]) if len(hero_cards) >= 4 else ('', '')
            _v1 = won_v[0] if app_sd and won_v else ''
            _vr = _v1.split()
            _h_pair = len(_hr[0]) == 2 and len(_hr[1]) == 2 and _hr[0][0] == _hr[1][0]
            _v_pair = len(_vr) == 2 and _vr[0][0] == _vr[1][0]
            if cooler_street == 'preflop' and _h_pair and _v_pair:
                cooler_kind = (f"PF pair-over-pair ({_vr[0][0]}{_vr[0][0]} > "
                               f"{_hr[0][0]}{_hr[0][0]}, analyst-identified)")
            elif cooler_street == 'preflop':
                cooler_kind = 'Preflop structural matchup (analyst-identified)'
            else:
                cooler_kind = 'Postflop structural matchup (analyst-identified)'
        cooler_hands.append({
            'id': hid,
            'tournament': h.get('tournament', '—'),
            'date': h.get('date', '—'),
            'hero': hero_cards or '—',
            'villain': villain_cards,
            'board': board_str or '—',
            'street': cooler_street,
            'kind': cooler_kind,
        })
    # B255 + BUG-5 (v7.99.38): cooler/flip/suckout priority ordering.
    # Explicit priority: (1) Lost flip (40-60% equity race), (2) Cooler
    # (Hero truly dominated, <40%), (3) Suckout (Hero favourite >60%, lost).
    # BUG-5 fix: the prior B255 code had two gaps:
    #   (a) `not _eai.get('won', True)` defaulted to True when `won` was
    #       missing → skipped reclassification for many all-in hands.
    #   (b) No fallback equity computation when hand wasn't in EAI list.
    # Fix: check `won is False` explicitly, and compute equity directly
    # from shown cards when EAI equity is unavailable.
    _eai_by_id = {}
    for _e in (s.get('eai', {}).get('hands', []) or []):
        _eai_by_id[_e.get('id', '')] = _e

    # Fallback equity from shown cards — import once
    try:
        from gem_pot_odds import enumerate_equity as _enum_eq
    except Exception:
        _enum_eq = None

    _suckout_reclassified = []
    _flip_reclassified = []
    _true_coolers = []
    for c in cooler_hands:
        _hid = c.get('id', '')
        # Look up full hand for won/lost status
        _full = hands_by_id_full.get(_hid, {})
        _won = _full.get('won')
        # Also check EAI entry
        _eai = _eai_by_id.get(_hid)
        if _eai and _eai.get('won') is not None:
            _won = _eai['won']

        # Only reclassify LOST hands (negative coolers)
        if _won is not False:
            _true_coolers.append(c)
            continue

        # Get equity — prefer EAI, fall back to direct enumeration
        _eq = None
        if _eai:
            _eq = _eai.get('hero_equity') or _eai.get('equity_at_allin')
        if _eq is None and _enum_eq:
            # Compute directly from hero/villain/board cards
            _hero_cards_str = c.get('hero', '')
            _vill_cards_str = c.get('villain', '')
            _board_str = c.get('board', '')
            if _hero_cards_str and _vill_cards_str:
                try:
                    _hc = [_hero_cards_str[i:i+2] for i in range(0, len(_hero_cards_str), 2)]
                    _vc = [[_vill_cards_str[i:i+2] for i in range(0, len(_vill_cards_str), 2)]]
                    _bd = _board_str.split() if isinstance(_board_str, str) else list(_board_str or [])
                    _bd = [x for x in _bd if len(x) == 2]  # clean
                    if len(_hc) == 2 and len(_vc[0]) == 2:
                        _raw_eq = _enum_eq(_hc, _vc, _bd[:3] if _bd else [])
                        if _raw_eq is not None:
                            _eq = _raw_eq / 100.0  # normalize to 0-1
                except Exception:
                    pass

        if _eq is None:
            _true_coolers.append(c)
            continue

        # Priority ordering: flip (40-60%) > cooler (<40%) > suckout (>60%)
        if 0.40 <= _eq <= 0.60:
            _flip_reclassified.append(c)
        elif _eq > 0.60:
            _suckout_reclassified.append(c)
        else:
            _true_coolers.append(c)
    # v8.12.4 (QA item 5): when the post-analyst refresh produced the
    # canonical cooler ledger (rd['cooler_ledger']), its classification is
    # authoritative — the attribution row reads the same ledger, so the
    # "7 negative coolers here / 6 actual there" split cannot recur.
    _cl = rd.get('cooler_ledger') or {}
    if _cl.get('negative_ids') is not None:
        _disp_by_id = {c.get('id'): c for c in
                       (_true_coolers + _flip_reclassified + _suckout_reclassified)}
        cooler_hands = [_disp_by_id[i] for i in _cl['negative_ids']
                        if i in _disp_by_id]
        _flip_reclassified = [_disp_by_id[i]
                              for i in _cl.get('flip_reclassified_ids', [])
                              if i in _disp_by_id]
        _suckout_reclassified = [_disp_by_id[i]
                                 for i in _cl.get('suckout_reclassified_ids', [])
                                 if i in _disp_by_id]
    else:
        cooler_hands = _true_coolers
    cooler_count = len(cooler_hands)
    # F5 (v7.49): positive coolers (Hero underdog won) for variance balance
    positive_coolers = list(coolers.get('positive_hands', []))
    pos_count = len(positive_coolers)
    net_count = cooler_count - pos_count
    net_summary_extra = (f"; +{pos_count} positive (net {net_count:+d})"
                         if pos_count else "")
    # B181 (Ron 2026-05-25): header shows how the cooler rate sits vs the
    # expected band - explicit +/-% vs the band midpoint, not just the word.
    _c_rate = coolers.get('rate', 0) or 0
    _c_lo = coolers.get('expected_low', 0) or 0
    _c_hi = coolers.get('expected_high', 0) or 0
    _c_mid = (_c_lo + _c_hi) / 2.0
    _c_vs = coolers.get('vs_expected', '—')
    if _c_mid > 0:
        _c_rel = (_c_rate / _c_mid - 1.0) * 100.0
        _c_arrow = ('🔺' if _c_vs == 'above'
                    else '🔻' if _c_vs == 'below' else '▪️')
        _c_band = (f"{_c_rate:.2f}/100 vs {_c_lo:.2f}–{_c_hi:.2f} expected "
                   f"({_c_arrow} {_c_rel:+.0f}% vs midpoint, {_c_vs} band)")
    else:
        _c_band = f"{_c_rate:.2f}/100, {_c_vs} expected band"
    doc.subsection("sec-1-7", "S1.7 Confirmed Coolers",
                   f"{cooler_count} negative cooler(s){net_summary_extra}, "
                   f"{_c_band}")
    if not cooler_hands and not positive_coolers:
        doc.w("👍 No coolers this session.")
    else:
        # Phase 4.8: cooler definition text → tooltip on section, B214 note removed,
        # "#" column removed per user review.
        doc.w('<span data-tip="Cooler = unavoidable big-pot loss between two strong '
              'made hands. Action sequence may be sub-optimal but loss is structural '
              'to the matchup. Positive coolers (Hero underdog won) tracked separately '
              'below for variance-balance accounting."></span>')
        doc.w("")
        doc.w("| Hand Reference | Hero | Villain | Board | Street | Kind |")
        doc.w("|---|---|---|---|---|---|")
        # Build hand-id lookup so cooler entry inherits position/stack from full hand
        hands_by_id = {h.get('id',''): h for h in hands}
        # v8.12.4 (QA item 9): multiway villain cells carry "Xx Xx / Yy Yy" —
        # pill each hand separately so the separator survives (a flat pill
        # pass rendered 2 villains as one unreadable 4-card blob).
        def _villain_cell(v):
            v = v or '—'
            if '/' in v:
                return ' / '.join(_cards_str_to_pills(g.strip())
                                  for g in v.split('/') if g.strip())
            return _cards_str_to_pills(v)
        for i, c in enumerate(cooler_hands, 1):
            full = hands_by_id.get(c.get('id',''), {})
            merged = {
                'id': c.get('id',''),
                'tournament': c.get('tournament', full.get('tournament','—')),
                'date': c.get('date', full.get('date','—')),
                'position': full.get('position', '—'),
                'stack_bb': full.get('stack_bb', 0),
            }
            # B155 (Ron 2026-05-23): render hole cards / board as colored
            # pills (consistent with the rest of the report). hero/villain
            # are hole cards (sort desc); board is temporal (preserve order).
            doc.w(f"| {_hand_ref(merged)} | "
                  f"{_cards_str_to_pills(c.get('hero','—'))} | "
                  f"{_villain_cell(c.get('villain','—'))} | "
                  f"{_cards_text_to_pills(c.get('board','—'))} | "
                  f"{c.get('street','—')} | {c.get('kind','—')} |")
        doc.w("")
        # B255: surface reclassified suckouts/flips if any were removed from cooler table
        if _suckout_reclassified:
            doc.w(f"🤢 **{len(_suckout_reclassified)} hand(s) analyst-tagged as cooler "
                  f"but Hero was the equity favourite (suckout, not cooler):** "
                  + ', '.join(f"{_hand_ref(hands_by_id.get(c.get('id',''), c))}"
                              for c in _suckout_reclassified)
                  + " — see suckout ledger in S1.4.")
            doc.w("")
        if _flip_reclassified:
            doc.w(f"🪙 **{len(_flip_reclassified)} hand(s) analyst-tagged as cooler "
                  f"but equity was a flip (42–58%):** "
                  + ', '.join(f"{_hand_ref(hands_by_id.get(c.get('id',''), c))}"
                              for c in _flip_reclassified)
                  + " — reclassified as lost flip.")
            doc.w("")

        # F5 (v7.49): positive coolers — Hero underdog won. Surfaced as a
        # collapsible details block so the negative cooler list stays the
        # focus, but the variance balance is visible.
        if positive_coolers:
            doc.w("")
            doc.w(f"<details><summary><strong>🍀 {pos_count} positive cooler"
                  f"{'s' if pos_count != 1 else ''} (Hero underdog won) — click to expand</strong></summary>")
            doc.w("")
            doc.w("*Positive coolers are the mirror: Hero was on the wrong side of "
                  "a cooler-shaped matchup but hit (set vs overpair, runner-runner "
                  "FH, etc.). Over many sessions, these should approximately balance "
                  "negative coolers — net variance attribution = negative_count − positive_count.*")
            doc.w("")
            doc.w("| Hand Reference | Hero | Villain | Board | Street | Kind |")
            doc.w("|---|---|---|---|---|---|")
            for c in positive_coolers:
                full = hands_by_id.get(c.get('id',''), {})
                merged = {
                    'id': c.get('id',''),
                    'tournament': c.get('tournament', full.get('tournament','—')),
                    'date': c.get('date', full.get('date','—')),
                    'position': full.get('position', '—'),
                    'stack_bb': full.get('stack_bb', 0),
                }
                doc.w(f"| {_hand_ref(merged)} | "
                      f"{_cards_str_to_pills(c.get('hero','—'))} | "
                      f"{_villain_cell(c.get('villain','—'))} | "
                      f"{_cards_text_to_pills(c.get('board','—'))} | "
                      f"{c.get('street','—')} | {c.get('kind','—')} |")
            doc.w("")
            doc.w(f"*Net cooler variance this session: **{net_count:+d}** "
                  f"({cooler_count} negative − {pos_count} positive). "
                  f"Negative = bad variance accumulated; positive = lucky pickups.*")
            doc.w("")
            doc.w("</details>")
            doc.w("")

    # I.8 Phase Distribution / Tournament Phases
    doc.subsection("sec-1-8", "S1.8 Phase Distribution",
                   "where the hands came from + variance posture")
    phase_dist = rd.get('tournament_phase_dist', [])
    if phase_dist:
        # Phase 4.8: column reorder per user review — Status first.
        doc.w("| Status | Phase | % | Benchmark | Hands |")
        doc.w("|:---:|---|---|---|---|")
        for p in phase_dist:
            doc.w(f"| {p.get('indicator', p.get('flag','⚪'))} | "
                  f"{p.get('phase','—')} | "
                  f"{p.get('pct',0):.1f}% | {p.get('benchmark','—')} | "
                  f"{p.get('hands',0)} |")
        doc.w("")
        # B173 (Ron 2026-05-24): one-line reading guide so the table is
        # self-explanatory — what the % and Status columns actually mean.
        doc.w("*How to read: **%** is the share of this session's hands played in "
              "each tournament phase; **Benchmark** is the share a typical MTT "
              "volume profile produces. **Status** flags over- or under-"
              "representation — a late-phase skew means more ICM-pressured, higher-"
              "variance spots; an early-phase skew means more deep-stack play. It "
              "frames variance posture, not skill.*")
        doc.w("")
        # v8.12.4 (QA item 18): Del-6 phase-type classification line.
        _pp_d18 = rd.get('phase_pattern')
        if _pp_d18:
            doc.w(f"{_pp_d18.get('emoji','🔴')} **{_pp_d18.get('label','')}** — "
                  f"{_pp_d18.get('detail','')}")
            if _pp_d18.get('caveat'):
                doc.w(f"*{_pp_d18['caveat']}*")
            doc.w("")

    # I.9 Intra-Session Arc
    arc = s.get('intra_session_arc', {})
    quartiles = arc.get('quartiles', [])
    doc.subsection("sec-1-9", "S1.9 Intra-Session Arc",
                   "fatigue / tilt detection across session quartiles")
    if quartiles:
        # B177 (Ron 2026-05-25): cEV/100 column - the spine unit. BB/100 does
        # not aggregate across MTT blind levels, so the arc is read in cEV
        # (% of starting stack /100) with BB/100 kept as the secondary lens.
        # Phase 4.8 v3: removed Hands column per user review
        # B220 (Item 3): cev_per_100 is a fraction — same units as
        # cev_session.cev_per_stack_per_100 from gem_cev.py. Weighted average
        # across quartiles (Σ cev_per_100_q * n_resolved_q / Σ n_resolved_q)
        # reconciles with session cEV/100. Display multiplies by 100 for %.
        # v8.14.0 Slice E (copy clarity): one concise gloss for the two
        # rate units so the acronyms are not unexplained in the body.
        doc.w("*cEV/100 = chip-EV per 100 hands (% of starting stack); "
              "BB/100 = big blinds won per 100 hands. cEV/100 is the spine "
              "metric because BB/100 does not aggregate across MTT blind "
              "levels.*")
        doc.w("")
        doc.w("| Quartile | VPIP | Mistakes/100 | cEV/100 | BB/100 | Time Range |")
        doc.w("|---|---|---|---|---|---|")
        for q in quartiles:
            mst = q.get('mistakes_per_100', 0)
            mst_e = "🟢" if mst < 1.0 else ("🟡" if mst < 1.5 else "🔴")
            bb = q.get('bb_per_100', 0)
            bb_e = "🔴" if bb < -50 else ("🟢" if bb > 0 else "🟡")
            cev = q.get('cev_per_100')
            if cev is None:
                cev_cell = "—"
            else:
                # B220: cev_per_100 is a fraction (same units as
                # cev_session.cev_per_stack_per_100) — multiply by 100 for
                # percentage display, matching _cevcell() convention.
                cev_pct = cev * 100
                cev_e = ("🔴" if cev_pct < -5 else
                         ("🟢" if cev_pct >= 0 else "🟡"))
                cev_cell = f"{cev_e} {cev_pct:+.1f}%"
            t_first = q.get('first_time', '—')
            t_last = q.get('last_time', '—')
            # B179: a quartile can legitimately span midnight (session runs
            # past 00:00). Hands are now ordered by deal-order hand-id, so
            # last_time < first_time as clock strings means the quartile
            # crossed into the next day — mark it so the range isn't read
            # as backwards.
            if t_first != '—' and t_last != '—':
                time_range = f"{t_first} → {t_last}"
                if t_last < t_first:
                    time_range += " (+1d)"
            else:
                time_range = q.get('time_range', '—')
            doc.w(f"| Q{q.get('quartile','?')} | "
                  f"{q.get('vpip',0):.1f}% | {mst_e} {mst:.2f} | "
                  f"{cev_cell} | {bb_e} {bb:+.1f} | {time_range} |")
        doc.w("")
        # v8.12.4 (QA item 23): this section claims fatigue/tilt detection —
        # draw the conclusion instead of leaving four colored rows. A fatigue
        # arc means DETERIORATION across quartiles; uniform red is a
        # session-wide signal, not an arc.
        _cevs_arc = [q.get('cev_per_100') for q in quartiles
                     if q.get('cev_per_100') is not None]
        if len(_cevs_arc) >= 3:
            _all_neg = all(c < 0 for c in _cevs_arc)
            _all_pos = all(c >= 0 for c in _cevs_arc)
            _worsening = (_cevs_arc[-1] < _cevs_arc[0]
                          and _cevs_arc[-1] == min(_cevs_arc))
            if _all_neg and not arc.get('tilt_flag'):
                doc.w("📐 **Arc verdict: no fatigue signature.** Every "
                      "quartile ran cEV-negative at similar magnitude — "
                      "that is a session-wide pattern (variance and/or a "
                      "systematic leak), not a late-session deterioration. "
                      "Fatigue/tilt would show Q1-Q2 healthy and Q3-Q4 "
                      "collapsing.")
                doc.w("")
            elif _all_pos:
                doc.w("📐 **Arc verdict: stable.** All quartiles ran "
                      "cEV-positive — no fatigue signature.")
                doc.w("")
            elif _worsening and not arc.get('tilt_flag'):
                doc.w("📐 **Arc verdict: deteriorating trend** — the final "
                      "quartile is the session's worst. Below the tilt-flag "
                      "threshold, but worth a look at the late hands.")
                doc.w("")
        # Tilt flag
        tilt_flag = arc.get('tilt_flag', False)
        tilt_note = arc.get('tilt_note', '')
        if tilt_flag:
            if tilt_note:
                doc.w(f"🔴 **Tilt flag raised:** {tilt_note}")
            else:
                doc.w("🔴 **Tilt flag raised:** late-session quartile deterioration detected.")
            doc.w("")


# ============================================================
# SECTION II — SESSION VERDICT & TOP-LINE KPIs
# ============================================================

def _emit_ii_verdict_kpis(doc, s, rd, hands):
    """S6 — Section II header + II.1 Heuristic Cheat Sheet + II.2 Top-Line KPIs."""
    skill = rd.get('skill_band', {})
    doc.section("sec-6", "S6. Session Verdict & Top-Line KPIs",
                f"{skill.get('emoji','⚪')} {skill.get('label','—')}")

    # Phase 4.8: Metric Watchlist — full table moved here from standalone
    # _emit_leak_watchlist(). Uses the 64-session cohort targets from
    # gem_meta_analysis.py. Falls back to simple 4-metric check if the
    # watchlist data isn't available.
    wl = rd.get('leak_watchlist')
    if wl and wl.get('session_metrics'):
        doc.subsection("sec-6-0", "S6.0 Metric Watchlist",
                       wl.get('verdict_line', 'metrics vs target'))
        # Top priority actions block
        top_actions = wl.get('top_actions', [])
        if top_actions:
            doc.w("**Top priority for this session:**")
            doc.w("")
            for a in top_actions:
                icon = {'red': '🔴', 'amber': '🟡', 'green': '🟢'}.get(a['status'], '⚪')
                _ta_sec = a.get('section', '')
                if _ta_sec:
                    # Use markdown link (not raw HTML) — bullets are markdown context
                    _ta_name = f'[{a["metric"]}](#{_ta_sec})'
                else:
                    _ta_name = a['metric']
                doc.w(f"- {icon} **{_ta_name}** = {a['value']}{a['arrow']} → {a['action']}")
            doc.w("")
        # v8.12.4 (QA item 16): cross-metric coherence notes (e.g. bluff rows
        # pointing in opposite directions = spot-selection leak).
        for _syn_note in (wl.get('synthesis_notes') or []):
            doc.w(_syn_note)
            doc.w("")
        # Full table
        doc.w("**Full watchlist** (priority levels: 1 = primary lever, 2 = secondary, 3 = supporting)")
        doc.w("")
        doc.w("| Metric | Value | Target | Window | Status | Pri | Action |")
        doc.w("|---|---:|---|---|:---:|:---:|---|")
        for item in wl['session_metrics']:
            icon = {'red': '🔴', 'amber': '🟡', 'green': '🟢'}.get(item['status'], '⚪')
            window_lbl = 'today' if item['window'] == 'session' else 'trajectory'
            # P1b: make metric label a link to its detail section when available
            _wl_sec = item.get('section', '')
            if _wl_sec and item['status'] in ('red', 'amber'):
                _wl_label = f'<a href="#{_wl_sec}" class="xref">{item["label"]}</a>'
            else:
                _wl_label = item['label']
            doc.w(f"| {_wl_label} | {item['value']} | {item['target_range']} | "
                  f"{window_lbl} | {icon} | {item['priority']} | {item['action']} |")
        doc.w("")
        # Batch 3 (#4): render per-metric breakdowns for red/amber items
        _red_amber = [i for i in wl['session_metrics']
                      if i['status'] in ('red', 'amber') and i.get('sub_breakdowns')]
        if _red_amber:
            doc.w(f"<details><summary><strong>Metric breakdowns (click to expand)</strong>{_new_badge('metric_drilldown')}</summary>")
            doc.w("")
            for item in _red_amber:
                _bd = item['sub_breakdowns']
                doc.w(f"**{item['label']}** = {item['value']} (target: {item['target_range']})")
                doc.w("")
                doc.w("| Dimension | Value | Sample |")
                doc.w("|---|---|---|")
                for b in _bd:
                    doc.w(f"| {b['dimension']} | {b['value']} | n={b['sample']} |")
                doc.w("")
            doc.w("</details>")
            doc.w("")
        doc.w(f"*Targets derived from May 2026 cohort (64 sessions, 1,090 bullets). "
              f"P25/P75 thresholds; top-quartile-by-logit averages used as 'aim' anchors. "
              f"Refit via gem_meta_analysis.py.*")
        doc.w("")
    else:
        # Fallback: simple 4-metric check when full watchlist not available
        doc.subsection("sec-6-0", "S6.0 Metric Watchlist",
                       "metrics currently below target")
        core = s.get('core', {})
        watchlist_items = []
        vpip = core.get('vpip', 0)
        pfr = core.get('pfr', 0)
        if vpip > 30: watchlist_items.append(f"VPIP {vpip:.1f}% (target ≤28%)")
        if pfr > 25: watchlist_items.append(f"PFR {pfr:.1f}% (target ≤22%)")
        af = core.get('af', 0)
        if isinstance(af, (int, float)) and af < 1.5:
            watchlist_items.append(f"AF {af:.2f} (target ≥1.5)")
        wtsd = core.get('wtsd', 0)
        if wtsd > 35: watchlist_items.append(f"WTSD {wtsd:.1f}% (target ≤33%)")
        if watchlist_items:
            doc.w("**Below-target metrics this session:**")
            doc.w("")
            for item in watchlist_items:
                doc.w(f"- ⚠️ {item}")
        else:
            doc.w("👍 All tracked metrics within target bands.")
        doc.w("")

    # II.1 Heuristic Cheat Sheet
    doc.subsection("sec-6-1", "S6.1 Heuristic Cheat Sheet",
                   "self-talk for next session's weakest spots")
    drills = _generate_cheat_sheet(s, rd, hands)
    for d in drills:
        doc.w(f"- *{d}*")
    doc.w("")

    # II.2 Top-Line KPIs (table-size split + Wilson CI on every row)
    doc.subsection("sec-6-2", "S6.2 Top-Line KPIs",
                   "color-coded headline subset with Wilson CI + sample-gate")
    ts_b = s['_table_size_breakdown']
    if ts_b:
        doc.w("**Table-size mix (VPIP context — verdicts use per-size targets):**")
        doc.w("")
        # Per-size targets (rough industry baselines)
        ts_targets = {
            '5': {'vpip': (28, 35), 'pfr': (22, 28)},
            '6': {'vpip': (22, 28), 'pfr': (18, 23)},
            '7': {'vpip': (20, 26), 'pfr': (16, 22)},
            '8': {'vpip': (18, 23), 'pfr': (14, 19)},
            '9': {'vpip': (16, 21), 'pfr': (13, 18)},
        }
        doc.w("| Table | Hands | VPIP% | VPIP target | PFR% | PFR target | Status | Net BB | bb/100 |")
        doc.w("|---|---|---|---|---|---|---|---|---|")
        for ts in sorted(ts_b.keys()):
            d = ts_b[ts]
            tgt = ts_targets.get(str(ts), {'vpip': (20, 28), 'pfr': (15, 22)})
            v_lo, v_hi = tgt['vpip']
            p_lo, p_hi = tgt['pfr']
            v_v = _verdict_pct(d['vpip_pct'], v_lo, v_hi, n=d['hands'])
            p_v = _verdict_pct(d['pfr_pct'], p_lo, p_hi, n=d['hands'])
            # Combined status: worst of the two
            order = {"🟢": 0, "🟡": 1, "🔴": 2, "⚪": -1}
            combined = max([v_v, p_v], key=lambda x: order.get(x, 0))
            doc.w(f"| {ts}-max | {d['hands']} | {d['vpip_pct']:.1f}% | "
                  f"{v_lo}-{v_hi}% | {d['pfr_pct']:.1f}% | {p_lo}-{p_hi}% | "
                  f"{combined} | {d['net_bb']:+.1f} | {d['bb_per_100']:+.1f} |")
        doc.w("")
        doc.w("*Per-size targets: 5-max wider than 6-max wider than 8-max. "
              "Aggregate VPIP/PFR (below) suspends verdict when mix is non-standard.*")
        doc.w("")

    core = s.get('core', {})
    csv = s.get('csv_row', {})
    fa = s.get('facing_action', {})
    # B42 (v7.50, Ron 2026-05-17): aim lookups from leak watchlist —
    # surfaces top-quartile-Ron empirical aim alongside the pool-baseline
    # target band in each top-line KPI row.
    _aim = _aim_lookup_from_watchlist(rd)

    doc.w("**Pre-Flop Engine:**")
    doc.w("")
    # VPIP (with table-size context) — raw string: uses _wilson_ci +
    # _verdict_pct (NOT _verdict_ci), dynamic weighted targets, per-cohort
    # sub-rows. Must stay manual to preserve exact computation.
    vpip = csv.get('VPIP', core.get('vpip', 0))
    n_hands = s.get('volume', {}).get('hands', 1)
    n_5 = ts_b.get('5', {}).get('hands', 0)
    n_8 = ts_b.get('8', {}).get('hands', 0)
    mix_standard = (n_5 / n_hands < 0.10 and n_8 / n_hands < 0.20) if n_hands else False
    vpip_ci_lo, vpip_ci_hi = _wilson_ci(round(vpip * n_hands / 100), n_hands)
    # Item 6 (Ron 2026-05-11): when mix is non-standard, compute the WEIGHTED
    # target band from the actual table-size composition and verdict against
    # THAT — old code emitted a blanket 🟡 which read as "leak" when VPIP was
    # actually in range for the weighted target.
    if mix_standard:
        vpip_target_lo, vpip_target_hi = 18, 25
        vpip_target_label = "18-25% (6-max)"
        vpip_note = "vol-into-pot"
    else:
        ts_targets_local = {
            '5': (28, 35), '6': (22, 28), '7': (20, 26),
            '8': (18, 23), '9': (16, 21),
        }
        wlo = whi = w_n = 0
        for ts, d in ts_b.items():
            tgt = ts_targets_local.get(str(ts), (20, 28))
            n_t = d.get('hands', 0)
            wlo += tgt[0] * n_t
            whi += tgt[1] * n_t
            w_n += n_t
        if w_n:
            vpip_target_lo = wlo / w_n
            vpip_target_hi = whi / w_n
            vpip_target_label = f"{vpip_target_lo:.0f}-{vpip_target_hi:.0f}% (weighted)"
        else:
            vpip_target_lo, vpip_target_hi = 18, 25
            vpip_target_label = "18-25% (6-max)"
        vpip_note = "weighted target from table-size mix"
    vpip_status = _verdict_pct(vpip, vpip_target_lo, vpip_target_hi,
                               n=n_hands, n_min=200)
    # B43 (v7.50): append watchlist VPIP aim to target cell
    _vpip_aim = _aim.get('VPIP', '')
    _vpip_target_cell = f"{vpip_target_label} · {_vpip_aim}" if _vpip_aim else vpip_target_label
    _vpip_ci_tip = (f'<span class="ci-tip" title="CI 90%: '
                    f'{vpip_ci_lo:.0f}-{vpip_ci_hi:.0f}%">ⓘ</span>')
    _vpip_mid = (vpip_target_lo + vpip_target_hi) / 2
    _vpip_delta = vpip - _vpip_mid
    _t1_rows = [
        (f"| VPIP | {vpip_status} | {vpip:.1f}% {_vpip_ci_tip} | "
         f"{_vpip_target_cell} | {_vpip_delta:+.1f} pp | n={n_hands} | "
         f"{vpip_note} |"),
    ]
    # B6 (Ron 2026-05-11): when table-size mix is non-standard, emit
    # per-cohort VPIP rows so each gets its own verdict against its own
    # target band. Aggregate verdict is mathematically defensible (weighted)
    # but per-cohort gives Ron the per-table-type signal.
    if not mix_standard:
        ts_block = s.get('vpip_pfr_by_table_size', {}) or {}
        for ts in sorted(ts_block.keys()):
            d = ts_block[ts]
            n_t = d.get('n', 0)
            if n_t < 50: continue  # skip tiny cohorts
            v_pct = d.get('vpip_pct', 0)
            v_tgt = d.get('vpip_target', [18, 25])
            v_status = _verdict_pct(v_pct, v_tgt[0], v_tgt[1], n=n_t, n_min=50)
            v_ci_lo, v_ci_hi = _wilson_ci(round(v_pct * n_t / 100), n_t)
            _v_ci_tip = (f'<span class="ci-tip" title="CI 90%: '
                         f'{v_ci_lo:.0f}-{v_ci_hi:.0f}%">ⓘ</span>')
            _v_mid = (v_tgt[0] + v_tgt[1]) / 2
            _v_delta = v_pct - _v_mid
            _t1_rows.append(
                f"| └ VPIP @ {ts}-max | {v_status} | {v_pct:.1f}% {_v_ci_tip} "
                f"| {v_tgt[0]}-{v_tgt[1]}% | {_v_delta:+.1f} pp | n={n_t} | "
                f"cohort-specific verdict |")

    # PFR
    pfr = csv.get('PFR', core.get('pfr', 0))
    _t1_rows.append(
        {"name": "PFR", "pct_mode": True, "pct": pfr, "n": n_hands,
         "target_lo": 14, "target_hi": 20, "notes": "PF raise rate",
         "link_to": "sec-8-1", "aim": _aim.get('PFR')})

    # 3-Bet
    tbet = csv.get('ThreeBet', 0)
    n_3b_opps = (fa.get('threebet_split', {}).get('ip', {}).get('opps', 0) +
                 fa.get('threebet_split', {}).get('oop', {}).get('opps', 0))
    if n_3b_opps == 0:
        n_3b_opps = n_hands
    _t1_rows.append(
        {"name": "3-Bet", "pct_mode": True, "pct": tbet, "n": n_3b_opps,
         "target_lo": 6, "target_hi": 9, "notes": "PF re-raise rate",
         "link_to": "sec-8-4", "aim": _aim.get('ThreeBet')})

    # Squeeze — B164 (Ron 2026-05-24): Hero's preflop squeeze frequency
    # (3-bet over an open + at least one cold-caller). Aggregated across
    # positions from core['squeeze_pct_by_pos'].
    _sqz_by_pos = core.get('squeeze_pct_by_pos', {}) or {}
    _sqz_ct = sum(p.get('count', 0) for p in _sqz_by_pos.values()
                  if isinstance(p, dict))
    _sqz_opp = sum(p.get('opps', 0) for p in _sqz_by_pos.values()
                   if isinstance(p, dict))
    _t1_rows.append(
        {"name": "Squeeze %", "x": _sqz_ct, "n": _sqz_opp,
         "target_lo": 5, "target_hi": 13,
         "notes": "PF 3-bet vs open + caller(s)", "link_to": "sec-8-4"})

    # Cold Call NB — FIXED: field is 'cc' not 'count', 'cc_pct' for rate
    cc_data = fa.get('cold_call_nb', {})
    cc_opps = cc_data.get('opps', 0)
    cc_n = cc_data.get('cc', 0)
    _t1_rows.append(
        {"name": "Cold Call (non-blind)", "x": cc_n, "n": cc_opps,
         "target_lo": 5, "target_hi": 15,
         "notes": "CO/HJ/MP flat (excl blinds)",
         "link_to": "sec-8-8", "aim": _aim.get('Cold_Call_NB')})

    # ATS (Attempt To Steal) — B156 (Ron 2026-05-23): headline steal-rate
    # KPI. Was present historically, regressed out of II.2. ATS aggregates
    # CO/BTN/SB first-in raises when folded to; it is a core preflop-pressure
    # metric and is currently watchlist-flagged, so it belongs in the headline.
    ats_ct = core.get('ats_ct', 0)
    ats_opps = core.get('ats_opps', 0)
    _t1_rows.append(
        {"name": "ATS", "x": ats_ct, "n": ats_opps,
         "target_lo": 35, "target_hi": 45,
         "notes": "CO/BTN/SB first-in raise when folded to",
         "link_to": "sec-8-1",
         "aim": _aim.get('ATS') or _aim.get('ATS_Raw')})
    # Per-position steal breakdown (informational sub-row, mirrors BB-def)
    btn_o = csv.get('BTN_Open', 0)
    co_o = csv.get('CO_Open', 0)
    sb_s = csv.get('SB_Steal', 0)
    _t1_rows.append(
        f"| ↳ steal breakdown | — | BTN {btn_o:.0f}% · CO {co_o:.0f}% · "
        f"SB {sb_s:.0f}% | — | — | — | informational |")

    # BB Defense vs Steal — FIXED: 'defend'/'defend_pct'
    bb_d = fa.get('bb_defense_vs_steal', {})
    bb_opps = bb_d.get('opps', 0)
    bb_n = bb_d.get('defend', 0)
    _t1_rows.append(
        {"name": "BB Def vs Steal", "x": bb_n, "n": bb_opps,
         "target_lo": 55, "target_hi": 65,
         "notes": "call+3b vs CO/BTN/SB", "link_to": "sec-11-9"})
    # Show breakdown
    if bb_opps > 0:
        bb_call = bb_d.get('call', 0)
        bb_3b = bb_d.get('three_bet', 0)
        _t1_rows.append(
            f"| ↳ call breakdown | — | {bb_call} call "
            f"({bb_d.get('call_pct',0):.1f}%) + {bb_3b} 3-bet "
            f"({bb_d.get('three_bet_pct',0):.1f}%) | — | — | — | "
            f"informational |")

    # SB Defense vs LP — FIXED: 'defend'/'defend_pct'
    sb_d = fa.get('sb_defense_vs_lp', {})
    sb_opps = sb_d.get('opps', 0)
    sb_n = sb_d.get('defend', 0)
    _t1_rows.append(
        {"name": "SB Def vs LP (J29)", "x": sb_n, "n": sb_opps,
         "target_lo": 30, "target_hi": 40,
         "notes": "vs CO/BTN open", "link_to": "sec-8-3"})

    # Hero 4-Bet (overall)
    h4b_n = core.get('hero_4bet_when_facing_3bet_n', 0)
    h4b_pct = core.get('hero_4bet_when_facing_3bet_pct', 0)
    _t1_rows.append(
        {"name": "Hero 4-Bet", "pct_mode": True, "pct": h4b_pct, "n": h4b_n,
         "target_lo": 5, "target_hi": 12,
         "notes": "Hero opened, faced 3b, 4-bet",
         "link_to": "sec-8-6", "aim": _aim.get('Hero_4Bet')})

    # Hero 5-Bet — fixed v7.43 (B47): now uses correct hero_5bet_when_faced_5bet_pct
    h5b_proper_n = core.get('hero_5bet_when_faced_5bet_n', 0)
    h5b_proper_pct = core.get('hero_5bet_when_faced_5bet_pct', 0)
    if h5b_proper_n == 0:
        _t1_rows.append(
            "| [Hero 5-Bet](#sec-8-7) | ⚪ | — | 15-25% | — | — | "
            "never faced 5-bet — of 4-bets that faced 5-bet — see IV.7 |")
    else:
        _t1_rows.append(
            {"name": "Hero 5-Bet", "pct_mode": True, "pct": h5b_proper_pct,
             "n": h5b_proper_n, "target_lo": 15, "target_hi": 25,
             "notes": "of 4-bets that faced 5-bet",
             "link_to": "sec-8-7"})

    doc.write_block(metric_table_block("t1-preflop-kpis", _t1_rows))
    doc.w("")

    doc.w("**Post-Flop Engine:**")
    doc.w("")
    # AF / AFq (no CI — derived ratios, raw strings to preserve exact computation)
    # B42 (v7.50): AF/CR-Flop carry watchlist aim annotations
    af = csv.get('AF', core.get('af', 0))
    afq = csv.get('AFq', core.get('afq', 0))
    _af_aim = _aim.get('AF', '')
    _af_tgt = f"1.5-3.0 · {_af_aim}" if _af_aim else "1.5-3.0"
    _af_delta = af - 2.25  # midpoint of 1.5-3.0
    _afq_delta = afq - 8.5  # midpoint of 5-12%
    _t2_rows = [
        (f"| [AF](#sec-11-10) | {_verdict_pct(af,1.5,3.0)} | {af:.2f} | "
         f"{_af_tgt} | {_af_delta:+.2f} | — | postflop B+R / Calls |"),
        (f"| [AFq](#sec-11-10) | {_verdict_pct(afq,5,12)} | {afq:.1f}% | "
         f"5-12% | {_afq_delta:+.1f} pp | — | postflop aggression freq |"),
    ]

    # CR Flop / Total — FIXED: field is 'flop_cr'/'flop_opp' (singular)
    cr = s.get('cr_frequency', {})
    _t2_rows.append(
        {"name": "Check-Raise Flop", "x": cr.get('flop_cr', 0),
         "n": cr.get('flop_opp', 0), "target_lo": 6, "target_hi": 8,
         "notes": "flop x/r as % saw-flop",
         "link_to": "sec-11-7", "aim": _aim.get('CR_Flop_Pct')})
    _t2_rows.append(
        {"name": "Check-Raise Total", "x": cr.get('total_cr', 0),
         "n": cr.get('total_opp', 0), "target_lo": 8, "target_hi": 12,
         "notes": "all streets x/r", "link_to": "sec-11-7"})

    # Fold to CB
    fcb_data = fa.get('vs_cbet', {})
    fcb_opps = fcb_data.get('opps', 0)
    fcb_count = fcb_data.get('fold_count', round(fcb_opps * (csv.get('Fold_to_CBet', 0) / 100)))
    _t2_rows.append(
        {"name": "Fold to CBet", "x": fcb_count, "n": fcb_opps,
         "target_lo": 50, "target_hi": 60, "notes": "facing flop cbet",
         "link_to": "sec-11-1"})

    # WTSD/WSD/WWSF/Non-SD
    n_sf = sum(1 for h in hands if h.get('vpip') and h.get('players_at_flop', 0) >= 2)
    wtsd = csv.get('WTSD_Vol', core.get('wtsd_vol', 0))
    _t2_rows.append(
        {"name": "WTSD (vol)", "pct_mode": True, "pct": wtsd, "n": n_sf,
         "target_lo": 25, "target_hi": 32, "notes": "went to SD"})
    wsd_n = sum(1 for h in hands if h.get('went_to_sd'))
    wsd_won = sum(1 for h in hands if h.get('went_to_sd') and h.get('won'))
    _t2_rows.append(
        {"name": "WSD (vol)", "x": wsd_won, "n": wsd_n,
         "target_lo": 50, "target_hi": 58, "notes": "won at SD"})

    wwsf_total = core.get('wwsf_total', n_sf)
    wwsf_ct = core.get('wwsf_ct', 0)
    _t2_rows.append(
        {"name": "WWSF", "x": wwsf_ct, "n": wwsf_total,
         "target_lo": 42, "target_hi": 48, "notes": "won-when-saw-flop"})

    nsd = csv.get('Non_SD_Win', core.get('non_sd_win', 0))
    nsd_ct = core.get('non_sd_ct', 0)
    nsd_n = round(nsd_ct / (nsd / 100)) if nsd > 0 else 0
    if nsd_n > 0:
        _t2_rows.append(
            {"name": "Non-SD Win", "x": nsd_ct, "n": nsd_n,
             "target_lo": 25, "target_hi": 35, "notes": "won w/o showdown"})
    else:
        _nsd_delta = nsd - 30  # midpoint of 25-35
        _t2_rows.append(
            f"| Non-SD Win | {_verdict_pct(nsd,25,35)} | {nsd:.1f}% | "
            f"25-35% | {_nsd_delta:+.1f} pp | — | won w/o SD |")

    sd_agg = csv.get('SD_Aggressor', core.get('sd_aggressor_pct', 0))
    sd_agg_n = core.get('sd_aggressor', 0)
    sd_agg_total = round(sd_agg_n / (sd_agg / 100)) if sd_agg > 0 else 0
    if sd_agg_total > 0:
        _t2_rows.append(
            {"name": "SD Aggressor", "x": sd_agg_n, "n": sd_agg_total,
             "target_lo": 40, "target_hi": 100,
             "notes": "aggressor's SD won %"})

    # Bluff profile — B159 (Ron 2026-05-23): the headline KPI table was
    # missing the bluff dimension entirely. Semi-bluff + pure-bluff rates as
    # % of all bet decisions, linked to the II.4 detail. Same numbers/targets
    # as II.4 so the headline answers "do I bluff enough?" at a glance.
    _bp = s.get('bluff_profile', {}) or {}
    _bp_total = _bp.get('total', 0)
    if _bp_total:
        _t2_rows.append(
            {"name": "Semi-Bluff %", "x": _bp.get('semi', 0), "n": _bp_total,
             "target_lo": 15, "target_hi": 30,
             "notes": "semi-bluffs as % of bet decisions",
             "link_to": "sec-7-2"})
        _t2_rows.append(
            {"name": "Pure Bluff %", "x": _bp.get('pure', 0), "n": _bp_total,
             "target_lo": 10, "target_hi": 20,
             "notes": "pure bluffs as % of bet decisions",
             "link_to": "sec-7-2"})

    doc.write_block(metric_table_block("t2-postflop-kpis", _t2_rows))
    doc.w("")

    # === Subsections gained from S7 (was Mental Game & Bluff Profile) ===
    # sec-7-1 Mental Game Analysis
    doc.subsection("sec-7-1", "S7.1 Mental Game Analysis",
                   "process discipline + emotional control signals")
    _emit_mental_game(doc, s, rd, hands)
    # sec-7-3 Exploits (Pool-Specific)
    from gem_report_draft.sections_mistakes import _emit_sub_exploits
    _emit_sub_exploits(doc, s, rd, hands)
    # sec-7-2 Bluff Profile
    _emit_sub_bluff_profile_kpi(doc, s, rd, hands)


def _emit_ii_mental_bluff(doc, s, rd, hands):
    """S7 — Coach: session reading, discipline, outcome drivers, priority items."""
    doc.section("sec-7", "S7. Coach",
                "session reading, discipline assessment, outcome drivers")

    # Coach.1 — Daily Summary (moved from S1)
    _emit_daily_summary_table(doc, rd)

    # Coach.2 — Discipline / Confidence (brief verdict; full analysis in KPIs)
    doc.subsection("sec-7-2c", "S7.2 Discipline / Confidence",
                   "process discipline + emotional control verdict")
    _dt = rd.get('discipline_tier', {}) or {}
    _hero = rd.get('hero_classification', {}) or {}
    if _dt:
        doc.w(f"**Discipline tier:** {_dt.get('emoji', '⚪')} "
              f"{_dt.get('label', '—')} — {_dt.get('one_liner', '')}")
        doc.w("")
        if _dt.get('detail'):
            doc.w(f"*{_dt['detail']}*")
            doc.w("")
    if _hero:
        doc.w(f"**Hero classification:** {_hero.get('emoji', '')} "
              f"{_hero.get('label', '—')}")
        doc.w("")
    if not _dt and not _hero:
        doc.w("⚪ Discipline assessment not available for this session.")
        doc.w("")

    # Coach.3 — OUTCOME DRIVERS (= Skill Index Movement, moved from S1)
    _emit_skill_index_movement(doc, rd)

    # Coach.4 — Priority Leaks / Watch Items
    doc.subsection("sec-7-4", "S7.4 Priority Leaks / Watch Items",
                   "leaks to work on next session")
    # Pull from leak_persistence current_leaks — same data as S5.1 Promoted Leaks
    promoted = (rd.get('leak_persistence', {}) or {}).get('current_leaks', [])
    if promoted:
        for i, leak in enumerate(promoted, 1):
            name = leak.get('name', leak.get('leak', '—')) if isinstance(leak, dict) else str(leak)
            doc.w(f"{i}. {name}")
    else:
        doc.w("⚪ No priority leaks this session.")
    doc.w("")

    # Coach.5 — Hands to Open First
    doc.subsection("sec-7-5", "S7.5 Hands to Open First",
                   "most actionable hands to review")
    punts = s.get('punts', {}).get('hands', []) or []
    mistakes = s.get('mistakes', []) or []
    # BUG-S: exclude analyst-cleared hands from the review queue.
    # III.3/III.0/III.5/I.7 verdicts mean the hand is resolved — showing
    # them in "mistakes to review" confuses the reader.
    _ac_s = rd.get('analyst_commentary', {}) or {}
    _cleared_ids = {hid for hid, c in _ac_s.items()
                    if isinstance(c, dict) and (c.get('verdict', '') or '').startswith(
                        ('III.0', 'III.3', 'III.5', 'I.7', 'no leak'))}
    _priority = []
    for p in punts[:5]:
        if p.get('id') and p['id'] not in _cleared_ids:
            _priority.append(p)
    for m in mistakes[:5]:
        if m.get('id') and m not in _priority and m['id'] not in _cleared_ids:
            _priority.append(m)
    if _priority:
        for h in _priority[:10]:
            ref = _hand_ref(h)
            net = h.get('net_bb', 0)
            doc.w(f"- {ref} · net {net:+.1f}BB")
    else:
        doc.w("⚪ No priority hands flagged.")
    doc.w("")


# ============================================================
# EXTRACTED HELPER SUBSECTION EMITTERS
# ============================================================

def _emit_sub_top_pnl_lines(doc, s, rd, hands):
    """Extracted from S1: sec-1-2 Top P&L Lines. Moves to Leaks (S3).
    Phase 4.8: Deep Runs split out to _emit_deep_runs (now in S1 Results)."""
    # I.2 Top P&L Lines (deep runs moved to sec-1-1 area per user review)
    doc.subsection("sec-1-2", "S1.2 Top P&L Lines",
                   "where the chips actually moved")
    losing = s.get('top_losing_lines', [])
    winning = s.get('top_winning_lines', [])
    # D1: merge losing + winning into one table.
    # Phase 4.8 v3: filter <5 count, sort by BB/h descending.
    combined_lines = []
    for ln in losing[:8]:
        if ln.get('count', 0) >= 5:
            combined_lines.append({**ln, '_dir': '🔴'})
    for ln in winning[:5]:
        if ln.get('count', 0) >= 5:
            combined_lines.append({**ln, '_dir': '🟢'})
    combined_lines.sort(key=lambda x: -abs(x.get('avg_bb', x.get('bb_per_hand', 0))))
    # Batch 4 (ACE-2): Flag recurring -EV line classes as habitual leaks
    _habitual = [ln for ln in (losing or [])
                 if ln.get('count', 0) >= 10 and ln.get('net_bb', 0) < -15]
    if _habitual:
        doc.w(f"**Recurring -EV patterns**{_new_badge('recurring_patterns')} ({len(_habitual)} line classes with "
              f">=10 occurrences and significant losses):")
        doc.w("")
        for ln in _habitual[:5]:
            _line_nice = ln.get('line', '?').replace('_', ' ')
            doc.w(f"- **{_line_nice}**: {ln['count']} hands, "
                  f"{ln['net_bb']:+.0f} BB total ({ln.get('avg_bb', 0):+.1f} BB/hand) "
                  f"— *habitual pattern, review for correction*")
        doc.w("")
    if combined_lines:
        doc.w("**Top P&L Lines** (biggest movers, win or lose):")
        doc.w("")
        doc.w("| ⇅ | Line | # | Net BB | BB/h | Confidence |")
        doc.w("|---|---|---|---|---|---|")
        for ln in combined_lines[:12]:
            avg = ln.get('avg_bb', ln.get('bb_per_hand', 0))
            # B-V10: top 10 best + worst so popup has >= 5 examples after
            # JS filters out hands without appendix cards
            _net_val = ln.get('net_bb', 0)
            _best = ln.get('top3_best', [])
            _worst = ln.get('top3_worst', [])
            _drill_ids = (_worst[:10] + _best[:10]) if _net_val < 0 else (_best[:10] + _worst[:10])
            _drill_ids = [h for h in _drill_ids if h][:20]
            if _drill_ids:
                _hids_str = ','.join(_drill_ids)
                _line_name = ln.get('line', '—').replace('_', ' ')
                _net_cell = (f'<a class="hand-list-trigger" href="#" '
                             f'data-hids="{_hids_str}" '
                             f'data-list-title="{_line_name} top hands ({len(_drill_ids)})">'
                             f'{_net_val:+.1f}</a>')
            else:
                _net_cell = f'{_net_val:+.1f}'
            _line_display = ln.get('line', '—').replace('_', ' ')
            doc.w(f"| {ln['_dir']} | {_line_display} | {ln.get('count',0)} | "
                  f"{_net_cell} | {avg:+.2f} | "
                  f"{ln.get('confidence','—')} |")
        doc.w("")


def _emit_deep_runs(doc, s, hands):
    """Deep Runs — Phase 4.8: moved from sec-1-2 to S1 Results (under P&L)."""
    deep = s.get('deep_runs', [])
    # B99 (Ron 2026-05-19): cap top 20, filter ≥100 hands, add BB/100 + True EV BB/100.
    # B111 (Ron 2026-05-19): the deep_runs records DON'T have net_bb/true_ev_bb
    # fields — they only have eai_won/eai_total/eai_expected and stack arc.
    # Compute net_bb by aggregating per-tournament hands; True EV BB/100 uses
    # the EAI delta in BB-equivalent (eai_won - eai_expected) × avg-all-in-pot.
    deep_filtered = [r for r in deep if r.get('hands', 0) >= 100][:20]
    if deep_filtered:
        # Pre-aggregate hand-level net_bb by tournament for BB/100 computation
        from collections import defaultdict
        tour_net_bb = defaultdict(float)
        tour_hand_count = defaultdict(int)
        for h in hands:
            tname = h.get('tournament', '')
            if tname:
                tour_net_bb[tname] += h.get('net_bb', 0) or 0
                tour_hand_count[tname] += 1
        # Use session-average all-in pot size as the multiplier for EAI BB
        # adjustment — rough but reasonable for True EV approximation.
        eai_hands_list = s.get('eai', {}).get('hands', []) or []
        _avg_ai_pot_bb = 35.0  # reasonable mid-stakes MTT default

        doc.w("**Deep Runs** *(start → peak → low → final BB, ≥100 hands, top 20):*")
        doc.w("")
        doc.w("| Tournament | Hands | Stack arc | BB/100 | True EV BB/100 | Premiums% | All-Ins |")
        doc.w("|---|---|---|---|---|---|---|")
        for run in deep_filtered:
            tour = _short_tournament(run.get('tournament', '—'), 38)
            tour_key = run.get('tournament', '')
            arc = (f"{run.get('start','?')}→{run.get('peak','?')}"
                   f"→{run.get('low','?')}→{run.get('final','?')}BB")
            prem = run.get('premiums_pct', 0)
            eai_won = run.get('eai_won', 0)
            eai_total = run.get('eai_total', 0)
            eai_exp = run.get('eai_expected', 0)
            # B68 (v7.49, Ron 2026-05-12): add percentage form to deep-run EAI.
            if eai_total:
                if eai_exp > 0:
                    delta_pct = 100.0 * (eai_won - eai_exp) / eai_exp
                    eai_str = f"{eai_won}/{eai_total} (exp {eai_exp:.1f}, {delta_pct:+.0f}%)"
                else:
                    eai_str = f"{eai_won}/{eai_total} (exp {eai_exp:.1f})"
            else:
                eai_str = "—"
            # B111: compute BB/100 from hand-aggregated net_bb (was reading
            # non-existent run['net_bb'] field → always 0).
            n_hands = run.get('hands', 0) or 1
            net_bb = tour_net_bb.get(tour_key, 0)
            bb_per_100 = (net_bb / n_hands) * 100 if n_hands else 0
            # True EV BB/100: subtract EAI variance (in BB) from net.
            # eai_variance_bb ≈ (eai_won - eai_expected) × avg_all_in_pot
            if eai_total > 0:
                eai_var_bb = (eai_won - eai_exp) * _avg_ai_pot_bb
                true_ev_bb = net_bb - eai_var_bb
                true_ev_per_100 = (true_ev_bb / n_hands) * 100 if n_hands else 0
                true_ev_str = f"{true_ev_per_100:+.1f}"
            else:
                true_ev_str = "—"
            doc.w(f"| {tour} | {run.get('hands',0)} | {arc} | {bb_per_100:+.1f} | "
                  f"{true_ev_str} | {prem:.1f}% | {eai_str} |")
        doc.w("")


def _neutral_unreviewed_large_loss_verdict(voc, auto_cooler=False, auto_label=None,
                                           complete=False):
    """v8.12.12 Obj-B: a large-loss hand with NO analyst verdict must not read
    as an exculpatory decision verdict (cooler / vs top-of-range / variance).
    Lead with the review STATUS and attach the auto-detector signal or the
    showdown result context SEPARATELY, so an unreviewed punt is never shown as
    justified / cooler / variance. (Reverses BUG-7's variance-as-default for
    unreviewed rows; analyst-confirmed verdicts are handled before this.)

    v8.14.3 Issue 2 (Ron 2026-06-15): when the report is ANALYST_COMPLETE a
    large loss that is OUTSIDE the required analyst need-set must NOT read as
    '⏳ awaiting analyst' — that contradicts the COMPLETE state. Lead instead
    with an explicit, NON-BLOCKING 'not individually graded' status. This is safe
    because the critical-coverage gate already forces ANALYST_PARTIAL while any
    CRITICAL loss is unreviewed, so when complete=True these are non-critical
    losses shown for transparency, not hidden. Still never imply justified /
    cooler / variance for an ungraded hand."""
    _ctx = {
        'top_of_range': 'ran into top of range',
        'suckout': 'lost as favourite (suckout)',
        'lost_flip': 'lost a flip',
        'semi_bluff_cooler': 'all-in variance',
    }
    _lead = ('➖ not individually graded — outside required review set'
             if complete else '⏳ awaiting analyst')
    if voc and voc in _ctx:
        return _lead + ' — showdown: ' + _ctx[voc]
    if auto_cooler:
        return _lead + ' — auto signal: cooler-shape'
    if auto_label:
        return _lead + ' — auto signal: ' + str(auto_label)
    return _lead + ('' if complete else ' review')


def _emit_sub_large_loss_audit(doc, s, rd, hands):
    """Extracted from S1: sec-1-3 Large-Loss Audit. Moves to Top Hands (S2)."""
    # I.3 Bust-Hand Audit (with _hand_ref everywhere)
    # v7.36: table format — scannable. Columns carry the rich per-hand context
    # (action sequence + key-decision narrative + 1-2-back observation pulled
    # from analyst_commentary) without expanding to a per-hand block.
    # I.3 Large-Loss Audit (formerly "Bust-Hand Audit")
    # B45 (v7.51, Ron 2026-05-18): section captures hands losing >25BB
    # regardless of whether Hero actually busted. Renamed and the header
    # now flags actual bustouts separately (where Hero stack ended at 0 or
    # extremely short) vs significant-loss-but-survived hands.
    busts = sorted([h for h in hands if h.get('net_bb', 0) < -25],
                   key=lambda h: h['net_bb'])
    # B45 (v7.51, Ron 2026-05-18): subdivide for clarity. Bustout heuristic:
    # starting stack + net_bb < 1.5 BB means Hero is at/near zero after the hand.
    # Approximation until parser exposes hero_stack_after_bb directly. Edge
    # cases: re-entry tournaments where Hero rebuys are correctly classified
    # as bustouts because this is the per-hand bustout, not the tournament
    # exit. Hands where Hero won money but lost a side-pot >25BB end up here
    # rarely; if net_bb < 0 and stack remains comfortable, treat as survived.
    def _is_bustout(h):
        starting = h.get('stack_bb', 0) or 0
        net = h.get('net_bb', 0) or 0
        return (starting + net) < 1.5
    actual_bustouts = [h for h in busts if _is_bustout(h)]
    survived = [h for h in busts if not _is_bustout(h)]
    sub_caption = f"{len(busts)} hands lost >25BB"
    if actual_bustouts and survived:
        sub_caption += f" ({len(actual_bustouts)} actual bustouts, {len(survived)} large losses but survived)"
    elif actual_bustouts:
        sub_caption += f" — all bustouts"
    elif survived:
        sub_caption += f" — all large losses, no bustouts in this set"
    doc.subsection("sec-1-3", "S1.3 Large-Loss Audit",
                   sub_caption + " — 1-2-action-back classification")
    cooler_ids = set()  # always defined — populated in else branch below
    if not busts:
        doc.w("👍 No hands lost more than 25BB.")
    else:
        # Build classification index from upstream sections to compute real pointers
        cooler_ids = set((c.get('id') or '') for c in
                          (rd.get('coolers') or s.get('coolers', {}).get('hands', []) or []))
        analyst = rd.get('analyst_commentary', {}) or {}
        # B26 fix: also harvest I.7 verdicts from analyst commentary (not just
        # auto-detector). When auto-detector misses a cooler but analyst pass
        # classifies it as I.7, the bust row was falling through to "awaiting
        # analyst" — same bug-class as v7.37 Bug#9 III.1 routing.
        i7_ids = {hid for hid, cmt in analyst.items()
                  if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('I.7')}
        cooler_ids = cooler_ids | i7_ids
        iii0_ids = {hid for hid, cmt in analyst.items()
                    if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.0')}
        iii1_ids = {hid for hid, cmt in analyst.items()
                    if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.1')}
        # B142: analyst-confirmed non-punt mistakes — routed to the mistakes
        # appendix, NOT shown as "awaiting analyst" or cleared.
        iii2_ids = {hid for hid, cmt in analyst.items()
                    if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.2')}
        # B40 fix: also recognize III.3 misapplied-heuristic verdicts in bust audit
        iii3_ids = {hid for hid, cmt in analyst.items()
                    if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.3')}
        iii4_ids = {hid for hid, cmt in analyst.items()
                    if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.4')}
        iii5_ids = {hid for hid, cmt in analyst.items()
                    if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.5')}

        # B217 (Ron review 2026-05-25): "Key Decision" was never filled — drop
        # it. Replace with a "Type" column (the same concise description used
        # in III.2 Confirmed Mistakes), placed AFTER the Verdict column. Rows
        # are ordered by category: punts → mistakes → read-dep → coolers →
        # suckouts → others, then by loss size within each.
        _f1_hdr = "| Hand Reference | Cards | Net | Board | Verdict | Type |"
        _f1_sep = "|---|---|---|---|---|---|"
        _f1_rows = []
        any_awaiting = False  # B187: footnote mentions the marker only if used

        def _bust_category(hid):
            """(rank, label) — rank drives the row order Ron asked for."""
            cmt_l = analyst.get(hid, {}) or {}
            oc = (cmt_l.get('outcome') or '').strip().lower()
            if hid in iii1_ids:
                return 1, cmt_l.get('label') or 'Punt'
            if hid in iii2_ids:
                return 2, cmt_l.get('label') or 'Strategic leak'
            if hid in iii4_ids:
                return 3, cmt_l.get('label') or 'Read-dependent'
            if hid in cooler_ids:
                return 4, cmt_l.get('label') or 'Cooler'
            if hid in iii3_ids and oc == 'suckout':
                return 5, cmt_l.get('label') or 'Suckout'
            if hid in iii0_ids:
                return 6, cmt_l.get('label') or 'GTO-Standard'
            if hid in iii3_ids:
                return 6, cmt_l.get('label') or 'Cleared'
            if hid in iii5_ids:
                return 6, cmt_l.get('label') or 'Justified'
            return 6, cmt_l.get('label') or '—'

        _bust_rows_sorted = sorted(
            busts[:12],
            key=lambda h: (_bust_category(h.get('id', ''))[0],
                           -abs(h.get('net_bb', 0))))
        for h in _bust_rows_sorted:
            hid = h.get('id', '')
            if hid in iii1_ids:
                verdict = f"👎 punt — {_xref('sec-2-1', label='S2.1')}"
            elif hid in iii2_ids:
                verdict = f"👎 mistake — {_xref('sec-17-4', label='S17.4')}"
            elif hid in iii0_ids:
                _oce, _oct = _outcome_label(analyst.get(hid, {}),
                                            default=('⚖️', 'GTO-Standard'))
                verdict = f"{_oce} {_oct} — {_xref('sec-13-1', label='S13.1')}"
            elif hid in iii3_ids:
                _oce, _oct = _outcome_label(analyst.get(hid, {}))
                verdict = f"{_oce} {_oct} — {_xref('sec-13-1', label='S13.1')}"
            elif hid in iii4_ids:
                verdict = f"📖 read-dep — {_xref('sec-13-2', label='S13.2')}"
            elif hid in iii5_ids:
                verdict = f"👍 justified — {_xref('sec-13-3', label='S13.3')}"
            elif hid in i7_ids:
                # analyst-CONFIRMED cooler (I.7) — a real decision verdict.
                verdict = f"❄️ cooler — {_xref('sec-1-7', label='S1.7')}"
            else:
                # v8.12.12 Obj-B: NO analyst verdict. Never imply justified /
                # cooler / variance for an unreviewed large loss — lead with
                # review status and attach the auto signal / showdown result
                # context separately (an auto-detected cooler is a SIGNAL, not
                # a verdict). Reverses BUG-7's variance-as-verdict default.
                _voc_raw = rd.get('variance_outcomes', {}).get(hid)
                _voc = _voc_raw['outcome'] if isinstance(_voc_raw, dict) else _voc_raw
                _auto_cooler = hid in cooler_ids          # auto-only (i7 handled above)
                _auto_label = ((rd.get('auto_resolved_labels') or {}).get(hid)
                               if hid in (rd.get('auto_resolved_ids') or []) else None)
                _rc_complete = ((rd.get('report_completeness', {}) or {}).get('state')
                                == 'ANALYST_COMPLETE')
                verdict = _neutral_unreviewed_large_loss_verdict(
                    _voc, _auto_cooler, _auto_label, complete=_rc_complete)
                # v8.14.3 Issue 2: only flag the ⏳ footnote when an actual
                # "awaiting" label was emitted (i.e. report is NOT complete).
                if not _rc_complete:
                    any_awaiting = True

            cards = _cards_str_to_pills(''.join(h.get('cards', [])))
            netbb = h.get('net_bb', 0)
            board_raw = h.get('board') or []
            if isinstance(board_raw, list) and board_raw:
                board_pills = ' '.join(_card_html(c) for c in board_raw)
                board = f'<span style="white-space:nowrap">{board_pills}</span>'
            else:
                board = str(board_raw) if board_raw else '—'
            type_text = _bust_category(hid)[1]
            _f1_rows.append(f"| {_hand_ref(h)} | {cards} | {netbb:+.1f} | "
                  f"{board} | {verdict} | {type_text} |")
        _f1_blk = hand_evidence_table_block("i3-large-loss", _f1_hdr, _f1_sep, _f1_rows)
        doc.write_block(_f1_blk)
        doc.w("")
        if len(busts) > 12:
            # FEAT-2 (Ron 2026-05-30): overflow hands as clickable popup
            _overflow_hids = ','.join(
                h.get('id', '') for h in busts[12:] if h.get('id'))
            _n_over = len(busts) - 12
            doc.w(f'*…and <a class="hand-list-trigger" href="#" '
                  f'data-hids="{_overflow_hids}" '
                  f'data-list-title="Large losses (overflow — {_n_over} hands)">'
                  f'{_n_over} more bust hand(s)</a> '
                  f'({_xref("sec-17-6", label="or see S17.6 ↓")}).*')
            doc.w("")
        doc.w("*The real strategic question for any bust hand is what happened "
              "1-2 decisions BEFORE the all-in, not the showdown card. Verdicts "
              "use the analyst-commentary classifications produced this run.*")
        if any_awaiting:
            # B187 (Ron 2026-05-25): only surface the awaiting-marker note when
            # a row actually carries it — otherwise the footnote reads as a
            # phantom "pending analyst" on a fully-resolved table.
            # v8.12.12 Obj-B: separate decision verdict from auto signal /
            # showdown context, and never present an unreviewed loss as luck.
            doc.w("")
            doc.w("*⏳ awaiting analyst = no decision verdict yet for that hand. "
                  "Any \"auto signal\" (e.g. cooler-shape) or \"showdown\" note "
                  "is detector/result context, NOT a decision-quality verdict — "
                  "an unreviewed loss is not 'unlucky' or 'justified' until the "
                  "analyst grades it. Ask Claude to classify these.*")
    doc.w("")

    # ---- BUSTOUT TABLE (under large-loss audit) ----
    # Per-tournament bustout: the last hand of each tournament where Hero busted.
    # Shows tournament name, bust hand, cards, stack at bust, net, verdict.
    from collections import defaultdict as _ddict_bust
    _by_tourney_bust = _ddict_bust(list)
    for h in hands:
        tid = h.get('tournament_id') or h.get('tournament', '')
        if tid:
            _by_tourney_bust[tid].append(h)

    _bust_rows = []
    for tid, t_hands in _by_tourney_bust.items():
        t_sorted = sorted(t_hands, key=lambda x: x.get('id', ''))
        last = t_sorted[-1]
        _starting = last.get('stack_bb', 0) or 0
        _net = last.get('net_bb', 0) or 0
        _stack_after = _starting + _net
        _is_bust = _stack_after < 1.5

        # v8.5.9: When last hand was <3BB, find the "real bust hand" —
        # the earlier hand where Hero lost >50% of their stack.
        _show_hand = last
        _bust_note = ''
        if _starting < 3 and len(t_sorted) > 1:
            for _bh in reversed(t_sorted[:-1]):
                _bh_stk = _bh.get('stack_bb', 0) or 0
                _bh_net = _bh.get('net_bb', 0) or 0
                if _bh_stk > 3 and abs(_bh_net) > _bh_stk * 0.5:
                    _show_hand = _bh
                    _bust_note = f' (crippled here; final at {_starting:.0f}BB)'
                    break

        # v8.7.9 FIX: For survived tournaments, don't show a meaningless
        # preflop fold as the "exit hand." Find the biggest loss hand instead,
        # or if no significant hand, show the last VPIP hand.
        if not _is_bust:
            # Find biggest single-hand loss in this tournament
            _biggest_loss = min(t_sorted, key=lambda h: h.get('net_bb', 0) or 0)
            _bl_net = _biggest_loss.get('net_bb', 0) or 0
            if _bl_net < -3:
                # Show the crippling/biggest-loss hand
                _show_hand = _biggest_loss
                _bust_note = ''
            else:
                # No significant loss — show last VPIP hand (not a random fold)
                _vpip_hands = [h for h in t_sorted if h.get('vpip')]
                if _vpip_hands:
                    _show_hand = _vpip_hands[-1]
                # else keep last hand as fallback

        _tname = _show_hand.get('tournament', '')[:40]
        # v8.8.5: tournament context tag
        _tfmt = _show_hand.get('format', '')
        _fmt_tags = {'SATELLITE': ' [Satellite]', 'RACER': ' [Racer]',
                     'MYSTERY_BOUNTY': ' [Mystery]'}
        _tname += _fmt_tags.get(_tfmt, '')
        _cards = _cards_str_to_pills(''.join(_show_hand.get('cards', [])))
        _hid = _show_hand.get('id', '')
        _sh_starting = _show_hand.get('stack_bb', 0) or 0
        _sh_net = _show_hand.get('net_bb', 0) or 0

        # Verdict from analyst
        _ac_bust = (rd.get('analyst_commentary') or {}).get(_hid, {})
        _verdict_bust = ''
        if isinstance(_ac_bust, dict) and _ac_bust.get('verdict'):
            _verdict_bust = _ac_bust['verdict']
        elif _hid in cooler_ids:
            _verdict_bust = 'I.7 Cooler'
        # EAI equity if available
        _eai_bust = None
        for _e in (s.get('eai', {}).get('hands', []) or []):
            if _e.get('id') == _hid:
                _eq = _e.get('hero_equity')
                if _eq is not None:
                    _eai_bust = f"{(_eq * 100 if _eq <= 1.5 else _eq):.0f}%"
                break
        _eq_cell = _eai_bust or '—'
        _bust_ref = _hand_ref_id_only(_show_hand)
        # v8.8.5: %Lost = percent of hero starting stack lost (integer, no decimals)
        _pct_lost = 100 if _is_bust else (round(abs(_sh_net) / _sh_starting * 100) if _sh_starting > 0 else 0)
        _bust_rows.append((
            _tname, _bust_ref, _cards, f"{_sh_starting:.0f}BB",
            f"{_pct_lost}%", _eq_cell,
            (_verdict_bust or ('busted' if _is_bust else 'survived')) + _bust_note,
            len(t_hands),
            _sh_net,  # sort key (numerical, for sorting)
        ))

    if _bust_rows:
        _bust_rows.sort(key=lambda x: x[8])  # sort by net (worst first)
        _bust_rows = _bust_rows[:20]  # cap at 20
        _n_busted = sum(1 for r in _bust_rows if 'busted' in r[6].lower() or 'Cooler' in r[6] or 'III.' in r[6])
        doc.w(f"**Tournament Exits**{_new_badge('bustout_table')} "
              f"({len(_bust_rows)} tournaments, {_n_busted} busted):")
        doc.w("")
        doc.w("| Tournament | Exit Hand | Cards | Stack | %Lost | Equity | Result | Hands |")
        doc.w("|---|---|---|---|---|---|---|---|")
        for row in _bust_rows:
            # Obj-H: strip the verdict code at DISPLAY time only — row[6] keeps
            # the raw code so the _n_busted count above still recognises it.
            doc.w(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | "
                  f"{row[5]} | {_verdict_display_label(row[6])} | {row[7]} |")
        doc.w("")


def _emit_sub_bluff_profile_kpi(doc, s, rd, hands):
    """Extracted from S7: sec-7-2 Bluff Profile. Moves to KPIs (S6)."""
    # II.4 Bluff Profile (with Wilson CI)
    # Phase 4.8: removed "sample-gated + Wilson CI" from summary, status as first column,
    # removed count per category from text line (per user review).
    doc.subsection("sec-7-2", "S7.2 Bluff Profile",
                   "do I bluff enough?")
    bp = s.get('bluff_profile', {})
    total = bp.get('total', 0)
    pure_n = bp.get('pure', 0)
    semi_n = bp.get('semi', 0)
    value_n = bp.get('value', 0)
    if total == 0:
        doc.w("⚪ No bluff samples this session.")
    else:
        doc.w(f"**Total bet decisions analyzed: {total}**")
        doc.w("")
        doc.w("| Status | Class | Rate | CI 90% | Target | Count |")
        doc.w("|:---:|---|---|---|---|---|")
        # Hand IDs for popup drill-down
        from gem_report_draft._helpers import _popup_example_ids, _popup_title_with_count
        _bp_id_map = {
            'Value Bet': bp.get('value_ids', []),
            'Semi-Bluff': bp.get('semi_ids', []),
            'Pure Bluff': bp.get('pure_ids', []),
        }
        for label, x, lo, hi in [
            ('Value Bet', value_n, 50, 70),
            ('Semi-Bluff', semi_n, 15, 30),
            ('Pure Bluff', pure_n, 10, 20),
        ]:
            rate = 100.0 * x / total if total else 0
            ci_lo, ci_hi = _wilson_ci(x, total)
            verdict = _verdict_ci(x, total, lo, hi, n_min=10)
            # S7.2 feature: clickable count with hand-list popup
            _bp_pool = list(set(_bp_id_map.get(label, [])))
            _bp_sel = _popup_example_ids(_bp_pool)
            if _bp_sel and x > 0:
                _bp_str = ','.join(_bp_sel)
                _bp_title = _popup_title_with_count(f"{label} ({x})", len(_bp_pool))
                _cnt = (f'<a class="hand-list-trigger" href="#" '
                       f'data-hids="{_bp_str}" '
                       f'data-list-title="{_bp_title}">{x}</a>')
            else:
                _cnt = str(x)
            doc.w(f"| {verdict} | {label} | {rate:.1f}% | "
                  f"{ci_lo:.0f}-{ci_hi:.0f}% | {lo}-{hi}% | {_cnt} |")
        doc.w("")
        if total < 30:
            doc.w(f"*⚪ Total bet sample (n={total}) is below "
                  "comfortable verdict threshold; treat as directional only.*")
            doc.w("")


def _emit_section_ii(doc, s, rd, hands):
    """Section II wrapper — calls the two sub-emitters in original order."""
    _emit_ii_verdict_kpis(doc, s, rd, hands)
    _emit_ii_mental_bluff(doc, s, rd, hands)
