"""Sections IV through XII emitters."""

from gem_report_draft import _state
from gem_report_draft._helpers import (_wilson_ci, _clr, _clr_min, _clr_naive,
    _pctc, _stat_signal, _verdict_ci, _verdict_pct, _hand_ref, _hand_ref_short,
    _xref, _stat_row, _stat_row_pct, _aim_lookup_from_watchlist, _back_to_kpis,
    _compact_range, _run_emoji, _outcome_label, _CI_Z_DEFAULT, _MIN_N_FOR_SIGNAL,
    _RANK_ORD, _break_at_sentences, _href, _emit_correct_ranges, _AGG_GATE_LABELS, _agg_commentary,
    _popup_example_ids, _popup_title_with_count, _new_badge)
from gem_report_draft._html import (Doc, _card_html, _cards_html,
    _cards_str_to_pills, _cards_text_to_pills, _md_inline, _html_escape,
    _sort_cards_desc, _describe_made_hand, _SUIT_HTML, _RANK_VALUES, _SUIT_VALUES)
from gem_report_draft._hand_grid import (_render_hand_grid_table,
    _key_decision_action_class, _pick_key_action_idx, _hero_actions_by_street_from_app,
    _hero_action_verbs_by_street_from_app)
from gem_report_draft.sections_xiv import _generate_cheat_sheet
from gem_report_draft._blocks import (leak_bucket_overview_block,
    profile_matrix_block, hand_evidence_table_block, raw_reference_block,
    metric_table_block)

from collections import defaultdict

import gem_made_hands as mh
import gem_coaching as _coach

def _emit_section_iv(doc, s, rd, hands):
    # v8.5.4: hoist range loading to top of function — used by defend matrix,
    # cold-call, 3-bet profile, and all chart-derived lookups.
    _3b_ranges = {}
    _nhc_3b = lambda c: ''
    _hir_3b = lambda h, r: False
    _lr_3b = lambda: {}
    try:
        from gem_ranges import normalize_hand_class as _nhc_3b, hand_in_range as _hir_3b, load_ranges as _lr_3b
        _3b_ranges = _lr_3b()
    except Exception:
        pass

    core = s.get('core', {})
    csv = s.get('csv_row', {})
    doc.section("sec-8", "S8. The Pre-Flop Engine",
                f"VPIP {core.get('vpip',0):.1f}% / PFR {core.get('pfr',0):.1f}% / "
                f"3-Bet {csv.get('ThreeBet',0):.1f}%")

    # IV.1 Position Analysis (matrix + P&L + VPIP-PFR gap by depth)
    doc.subsection("sec-8-1", "S8.1 Position Analysis",
                   "VPIP/PFR by position + positional P&L + stack-depth")
    _back_to_kpis(doc)
    positions = s.get('positions', {})
    # Per-position open% target bands (rough 6-max baselines)
    # v7.43 (Ron 2026-05-09): SB target updated to align with J29 limp-heavy
    # framework. Old target 35-50% treated SB open as raise-only; J29 says
    # SB at 25-40BB BvB should be ~80% limp / ~10% raise / ~10% fold, so
    # total pot-entry rate ~85-95% (limp counts as entry). The matrix `Open%`
    # column counts both raises AND limps as opens, so target should be
    # 85-95% pot-entry. Hands at 25-40BB depth predominate; deeper stacks
    # (50BB+) shift toward more raises and the 35-50% raise-only target was
    # for that bucket. Until depth-bucketing is added, use J29 entry target.
    open_targets = {
        'UTG':   (10, 16),
        'UTG+1': (12, 18),
        'MP':    (14, 20),
        'HJ':    (18, 26),
        'CO':    (24, 32),
        'BTN':   (38, 50),
        'SB':    (85, 95),  # J29 pot-entry target (limp 80 + raise 10)
    }
    doc.w("**Position Matrix** *(open% verdict uses 6-max-style targets):*")
    doc.w("")
    # v7.36d: pre-compute per-position counts of Wide/Missed Open hands so the
    # matrix can link directly to XIII.1/XIII.3 sub-anchors per position.
    # B-V10: collect hand IDs per position for hand-list popups
    devs_for_links = s.get('preflop_deviations', [])
    wide_by_pos = {}
    missed_by_pos = {}
    _wide_ids_by_pos = {}
    _missed_ids_by_pos = {}
    for dv in devs_for_links:
        _dp = dv.get('pos', '?')
        _did = dv.get('id', '')
        if dv.get('type') == 'Wide Open':
            wide_by_pos[_dp] = wide_by_pos.get(_dp, 0) + 1
            _wide_ids_by_pos.setdefault(_dp, []).append(_did)
        elif dv.get('type') == 'Missed Open':
            missed_by_pos[_dp] = missed_by_pos.get(_dp, 0) + 1
            _missed_ids_by_pos.setdefault(_dp, []).append(_did)

    hdr = "| Position | Status | Rate | Target | Count | Opps | Notes | Hands | VPIP | PFR | Limps | Missed |"
    sep = "|---|---|---|---|---|---|---|---|---|---|---|---|"
    tbl_rows = []
    for pos in ['UTG', 'UTG+1', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB']:
        d = positions.get(pos, {})
        if d and d.get('hands', 0) > 0:
            op = d.get('open_pct', 0)
            fi = d.get('fi', 0)
            tgt = open_targets.get(pos)
            if pos == 'BB' or not tgt:
                tgt_str = "—"
                status = "—"
            else:
                lo, hi = tgt
                tgt_str = f"{lo}-{hi}%"
                status = _verdict_pct(op, lo, hi, n=fi, n_min=10)
            # Compose flagged-link cell → Notes column
            flagged_bits = []
            wide_n = wide_by_pos.get(pos, 0)
            missed_n = missed_by_pos.get(pos, 0)
            if wide_n > 0:
                _w_ids = [h for h in _wide_ids_by_pos.get(pos, []) if h][:20]
                if _w_ids:
                    _w_str = ','.join(_w_ids)
                    flagged_bits.append(
                        f'<a class="hand-list-trigger" href="#" '
                        f'data-hids="{_w_str}" '
                        f'data-list-title="Wide Opens from {pos} ({wide_n})">'
                        f'wide:{wide_n}</a>')
                else:
                    flagged_bits.append(f'wide:{wide_n}')
            if missed_n > 0:
                _m_ids = [h for h in _missed_ids_by_pos.get(pos, []) if h][:20]
                if _m_ids:
                    _m_str = ','.join(_m_ids)
                    flagged_bits.append(
                        f'<a class="hand-list-trigger" href="#" '
                        f'data-hids="{_m_str}" '
                        f'data-list-title="Missed Opens from {pos} ({missed_n})">'
                        f'missed:{missed_n}</a>')
                else:
                    flagged_bits.append(f'missed:{missed_n}')
            notes_cell = " · ".join(flagged_bits) if flagged_bits else "—"
            tbl_rows.append(f"| {pos} | {status} | {op:.1f}% | {tgt_str} | "
                  f"{d.get('opens',0)} | {fi} | {notes_cell} | "
                  f"{d.get('hands',0)} | {d.get('vpip',0):.1f}% | "
                  f"{d.get('pfr',0):.1f}% | {d.get('limps',0)} | {d.get('missed',0)} |")
    blk = profile_matrix_block("iv1-position-matrix", hdr, sep, tbl_rows)
    doc.write_block(blk)
    doc.w("")
    # Positional P&L with color-coding
    pnl = s.get('positional_pnl', {})
    if pnl:
        # Compute thresholds for color coding
        nets = [d.get('net_bb', 0) for d in pnl.values() if isinstance(d, dict)]
        if nets:
            nets_sorted = sorted(nets)
            big_loss = nets_sorted[0] if nets_sorted[0] < -20 else None
            big_win = nets_sorted[-1] if nets_sorted[-1] > 20 else None
        else:
            big_loss = big_win = None
        doc.w("**Positional P&L** *(🔴 = biggest loss, 🟢 = biggest win, ⚪ = small sample):*")
        doc.w("")
        # Phase 4.8: status first column per review
        doc.w("| Status | Pos | Hands | Net BB | bb/100 | VPIP Net BB | VPIP bb/h |")
        doc.w("|:---:|---|---|---|---|---|---|")
        for pos in ['UTG', 'UTG+1', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB']:
            d = pnl.get(pos, {})
            if d:
                net = d.get('net_bb', 0)
                hands_n = d.get('hands', 0)
                if hands_n < 20:
                    status = "⚪"
                elif net <= -50:
                    status = "🔴 big loss"
                elif net <= -20:
                    status = "🔴"
                elif net <= -5:
                    status = "🟡"
                elif net >= 50:
                    status = "🟢 big win"
                elif net >= 20:
                    status = "🟢"
                else:
                    status = "👍"
                # Collect VPIP hands (where Hero actually played) — JS
                # popup skips IDs with no appendix card, so preflop folds
                # that have no card won't show as empty rows.
                _pos_ids = [h['id'] for h in hands
                            if h.get('position') == pos and h.get('id')
                            and h.get('vpip')][:30]
                if _pos_ids:
                    _pos_str = ','.join(_pos_ids)
                    _hands_cell = (f'<a class="hand-list-trigger" href="#" '
                                   f'data-hids="{_pos_str}" '
                                   f'data-list-title="{pos} hands ({hands_n})">'
                                   f'{hands_n}</a>')
                else:
                    _hands_cell = str(hands_n)
                doc.w(f"| {status} | {pos} | {_hands_cell} | {net:+.1f} | "
                      f"{d.get('bb_per_100',0):+.1f} | "
                      f"{d.get('vpip_net_bb',0):+.1f} | "
                      f"{d.get('vpip_bb_per_hand',0):+.2f} |")
        doc.w("")
    # Stack depth distribution
    # Phase 4.8 fix: analyzer produces tier → {hands, vpip, pfr, ...} dicts,
    # not tier → int.  Extract 'hands' count from each bucket.
    sd = s.get('stack_depth', {})
    if sd:
        doc.w("**Stack-Depth Distribution:**")
        doc.w("")
        doc.w("| Bucket | Hands | % | VPIP | PFR | NB Gap |")
        doc.w("|---|---|---|---|---|---|")
        total_sd = sum(
            (v.get('hands', 0) if isinstance(v, dict) else v)
            for v in sd.values())
        for k in ['<12BB', '12-25BB', '25-40BB', '40BB+']:
            v = sd.get(k)
            if not v:
                continue
            if isinstance(v, dict):
                h_count = v.get('hands', 0)
                pct_v = 100 * h_count / total_sd if total_sd else 0
                doc.w(f"| {k} | {h_count} | {pct_v:.1f}% | "
                      f"{v.get('vpip',0):.1f}% | {v.get('pfr',0):.1f}% | "
                      f"{v.get('nb_gap',0):.1f}pp |")
            elif isinstance(v, (int, float)) and total_sd:
                doc.w(f"| {k} | {v} | {100*v/total_sd:.1f}% | — | — | — |")
        doc.w("")
    # VPIP-PFR Gap by Depth
    vpfr_gap = core.get('vpip_pfr_gap', 0)
    vpfr_gap_nb = core.get('vpip_pfr_gap_nonblind', 0)
    n_total = s.get('volume', {}).get('hands', len(hands))
    gap_nb_status = _verdict_pct(vpfr_gap_nb, 0, 5, n=n_total)
    doc.w(f"**VPIP-PFR Gap:** aggregate {vpfr_gap:.1f}pp, non-blind {vpfr_gap_nb:.1f}pp "
          f"({gap_nb_status} target <5pp non-blind = limited cold-call leak).")
    doc.w("")

    # IV.2 Preflop Deviations Summary (with proper denominator + range)
    doc.subsection("sec-8-2", "S8.2 Preflop Deviations Summary",
                   "chart-deviation buckets as % of opportunities — Detail column "
                   "links to per-position breakdown in XIII appendix")
    devs = s.get('deviation_summary', {})
    if devs:
        n_fi_total = sum(p.get('fi', 0) for p in positions.values())
        n_bb_steal = s.get('facing_action', {}).get('bb_defense_vs_steal', {}).get('opps', 0)
        n_bb_nonsteal = s.get('facing_action', {}).get('bb_defense_vs_nonsteal', {}).get('opps', 0)
        # v7.36d: each bucket maps to a XIII appendix anchor for the full list,
        # so Ron can click "Wide Open" in IV.2 → see all 14 wide-open hands grouped
        # by position in XIII.1.
        bucket_meta = {
            'Wide Open':                    (n_fi_total, "FI opps",            (0, 4),  'sec-xiii-1'),
            'Missed Open':                  (n_fi_total, "FI opps",            (0, 4),  'sec-xiii-3'),
            'Missed BB Defend':             (n_bb_steal+n_bb_nonsteal, "BB-faced-raise opps", (0, 5), None),
            'Wide BB Defend':               (n_bb_steal+n_bb_nonsteal, "BB-faced-raise opps", (0, 5), 'sec-xiii-2'),
            'Missed Defend/3-Bet':          (None, "facing-raise opps",        (0, 5), None),
            'Missed Rejam':                 (None, "<15BB facing-raise opps", (0, 5), None),
            'Wide Defend/3-Bet':            (None, "facing-raise opps",        (0, 5), None),
            'Wide BvB Iso (vs limp)':       (None, "BB-iso-vs-SB-limp opps",  (0, 8), None),
        }
        # B-V10: bucket name is the hand-list popup link (consistent with
        # how the rest of the report works). "Detail" column removed.
        hdr = "| Status | Bucket | Rate | Acceptable | Common Hands | Count/Denom |"
        sep = "|---|---|---|---|---|---|"
        tbl_rows = []
        for k, v in devs.items():
            if isinstance(v, dict) and v.get('count', 0) > 0:
                count = v.get('count', 0)
                meta = bucket_meta.get(k, (None, "—", (0, 5), None))
                denom, denom_label, target, anchor = meta
                common_str = ", ".join(str(x) for x in v.get('hands', [])[:6])
                # Make bucket name a hand-list popup
                _dev_ids = [hid for hid in (v.get('hand_ids') or []) if hid][:30]
                if _dev_ids:
                    _hstr = ','.join(_dev_ids)
                    _bucket_cell = (f'<a class="hand-list-trigger" href="#" '
                                    f'data-hids="{_hstr}" '
                                    f'data-list-title="{k} ({count} hands)">'
                                    f'{k}</a>')
                else:
                    _bucket_cell = k
                if denom and denom > 0:
                    rate = 100.0 * count / denom
                    verdict = _verdict_ci(count, denom, target[0], target[1], n_min=10)
                    tbl_rows.append(f"| {verdict} | {_bucket_cell} | "
                          f"{rate:.1f}% | {target[0]}-{target[1]}% | {common_str} | "
                          f"{count}/{denom} ({denom_label}) |")
                else:
                    tbl_rows.append(f"| ⚪ | {_bucket_cell} | "
                          f"— | {target[0]}-{target[1]}% | {common_str} | "
                          f"{count}/— ({denom_label}) |")
        blk = leak_bucket_overview_block("iv2-buckets", hdr, sep, tbl_rows)
        doc.write_block(blk)
        doc.w("")
        doc.w("*Per v7.35 D20: every flagged metric carries denominator + target band. "
              "Wide opens at 14/227 = 6.2% is barely above the 0-4% target — most "
              "are MARGINAL flags, not CLEAR leaks. Click \"see list\" to view the "
              "actual hands per position and verify against chart contents.*")
        doc.w("")
    # Phase 4.8 v3: removed "First 10 individual deviations" list from page
    # per user review — individual deviations only in popups / full lists
    # (XIII.1-XIII.3).

    # IV.3 Blind Combat
    doc.subsection("sec-8-3", "S8.3 Blind Combat",
                   "BvB / SB pot-entry / BB defense by opener")
    _back_to_kpis(doc)
    fa_local = s.get('facing_action', {})
    # D3 (Ron 2026-05-11): merge SB/BB defense rates into one overview table
    # with status dots, then break out BvB action distribution separately
    # since it's a different axis (action shares, not defense rate).
    sb_d = fa_local.get('sb_defense_vs_lp', {})
    bb_d = fa_local.get('bb_defense_vs_steal', {})
    bb_ns = fa_local.get('bb_defense_vs_nonsteal', {})
    overview_rows = []
    for label, blk, tgt_lo, tgt_hi, extra in [
        ('SB Defense vs LP (J29)', sb_d, 30, 40, ''),
        ('BB Defense vs Steal', bb_d, 55, 65,
         (f" · call {bb_d.get('call',0)} ({bb_d.get('call_pct',0):.1f}%) · "
          f"3-bet {bb_d.get('three_bet',0)} ({bb_d.get('three_bet_pct',0):.1f}%)") if bb_d else ''),
        ('BB Defense vs Non-Steal (EP/MP open)', bb_ns, 35, 50, ''),
    ]:
        if blk and blk.get('opps', 0) > 0:
            opps = blk.get('opps', 0)
            n = blk.get('defend', 0)
            pct = blk.get('defend_pct', 0)
            ci_lo, ci_hi = _wilson_ci(n, opps)
            verdict = _verdict_ci(n, opps, tgt_lo, tgt_hi, n_min=10)
            overview_rows.append({
                'label': label, 'n': n, 'opps': opps, 'pct': pct,
                'ci': (ci_lo, ci_hi), 'target': f'{tgt_lo}-{tgt_hi}%',
                'verdict': verdict, 'extra': extra,
            })
    if overview_rows:
        # B73 (v7.50, Ron 2026-05-12): use pre-computed example hand IDs from
        # rd['blind_combat_example_hands'] so they match what got promoted to
        # the appendix. Renderer and prep must use the same list.
        blind_examples = rd.get('blind_combat_example_hands', {}) or {}
        hands_by_id_local = s.get('_hands_by_id', {}) or {}
        # Use range-gated missed defend IDs when available
        _sb_gated = (fa_local.get('sb_defense_vs_lp') or {}).get('missed_defend_gated', [])
        _bb_gated = (fa_local.get('bb_defense_vs_steal') or {}).get('missed_defend_gated', [])
        _gated_by_label = {}
        if _sb_gated:
            _gated_by_label['SB Defense vs LP (J29)'] = _sb_gated
        if _bb_gated:
            _gated_by_label['BB Defense vs Steal'] = _bb_gated
        # Phase 4.8: status first column per review
        doc.w("| Status | Defense type | Rate | CI 90% | Target | Examples | Missed (in range) | Notes |")
        doc.w("|:---:|---|---|---|---|---|---|---|")
        for r in overview_rows:
            example_ids = blind_examples.get(r['label'], []) or []
            if example_ids:
                _ex_str = ','.join(example_ids[:10])
                ex_cell = (f'<a class="hand-list-trigger" href="#" '
                          f'data-hids="{_ex_str}" '
                          f'data-list-title="{r["label"]} examples ({len(example_ids)})">'
                          f'{len(example_ids)}</a>')
            else:
                ex_cell = '—'
            # Missed defend — range-gated hands with explanations
            _gated = _gated_by_label.get(r['label'], [])
            if _gated:
                _g_ids = [g['id'] for g in _gated]
                _g_str = ','.join(_g_ids[:15])
                _g_title = f"Missed {r['label']} — hands in defend range ({len(_gated)})"
                missed_cell = (f'<a class="hand-list-trigger" href="#" '
                              f'data-hids="{_g_str}" '
                              f'data-list-title="{_g_title}">'
                              f'{len(_gated)} missed</a>')
            else:
                missed_cell = '—'
            doc.w(f"| {r['verdict']} | {r['label']} | "
                  f"{r['pct']:.1f}% ({r['n']}/{r['opps']}) | "
                  f"{r['ci'][0]:.0f}-{r['ci'][1]:.0f}% | {r['target']} | "
                  f"{ex_cell} | {missed_cell} | {r['extra']} |")
        doc.w("")
        # Item 9: SB + BB defend matrices by opener position.
        # Replaces the flat "Folded SB-vs-LP spots" list with per-opener
        # matrices showing rate, CI, delta, missed/wrong defend counts.
        _pos_rank = {'UTG': 0, 'UTG+1': 1, 'MP': 2, 'HJ': 3, 'CO': 4,
                     'BTN': 5, 'SB': 6, 'BB': 7}
        _LP_POS = {'CO', 'BTN'}

        # BUG-10 (Ron review 2026-05-31): expected defend range by node.
        # Each missed-defense hand must show the expected range and why
        # Hero's hand fits it.
        _DEFEND_RANGES = {
            # BB vs steal: defend ~55-65% of hands
            ('BB', 'BTN'): ('22+, A2s+, K2s+, Q5s+, J7s+, T8s+, 97s+, 86s+, '
                            'A2o+, K7o+, Q9o+, J9o+, T9o', '~60% defend'),
            ('BB', 'CO'):  ('22+, A2s+, K4s+, Q7s+, J8s+, T8s+, 98s, '
                            'A3o+, K9o+, QTo+, JTo', '~55% defend'),
            ('BB', 'SB'):  ('22+, A2s+, K2s+, Q2s+, J4s+, T6s+, 96s+, 85s+, 75s+, '
                            'A2o+, K4o+, Q7o+, J8o+, T8o+', '~70% defend'),
            ('BB', 'HJ'):  ('33+, A2s+, K7s+, Q9s+, J9s+, T9s, '
                            'A7o+, KTo+, QJo', '~45% defend'),
            ('BB', 'MP'):  ('55+, A5s+, K9s+, QTs+, JTs, '
                            'A9o+, KJo+', '~35% defend'),
            ('BB', 'UTG'):  ('77+, A9s+, KTs+, QJs, ATo+, KQo', '~25% defend'),
            ('BB', 'UTG+1'):('77+, A8s+, KTs+, QJs, ATo+, KQo', '~28% defend'),
            # SB vs LP: defend ~30-40% (mix of 3-bet + some flats)
            ('SB', 'BTN'): ('55+, A4s+, K9s+, QTs+, JTs, A9o+, KQo', '~35% defend (3-bet + flat)'),
            ('SB', 'CO'):  ('77+, A8s+, KTs+, QJs, ATo+, KQo', '~30% defend (3-bet + flat)'),
            # BUG-K: SB vs EP/MP = 3-bet or fold (flat ~0% OOP — invites squeeze, bloated pot)
            ('SB', 'HJ'):  ('88+, ATs+, KQs, AJo+, KQo', '~20% 3-bet/fold (flat~0)'),
            ('SB', 'MP'):  ('99+, AJs+, KQs, AQo+', '~15% 3-bet/fold (flat~0)'),
            ('SB', 'UTG'):  ('TT+, AQs+, AKo', '~10% 3-bet/fold (flat~0)'),
            ('SB', 'UTG+1'):('TT+, AQs+, AKo', '~10% 3-bet/fold (flat~0)'),
        }

        def _defend_range_note(hero_pos, opener_pos, hero_cards_str):
            """Return (expected_range, membership_note) for a missed-defense hand.
            v8.5.3: uses SBD/BBD charts when available, falls back to hardcoded."""
            # Try SBD/BBD charts first
            _chart_range = None
            _chart_name = None
            if hero_pos == 'SB':
                for _dk in ('35BB', '50BB', '20BB'):
                    _ck = f'SBD_{_dk}_vs{opener_pos}'
                    _cr = _3b_ranges.get(_ck, {})
                    if _cr:
                        _chart_range = _cr
                        _chart_name = _ck
                        break
            elif hero_pos == 'BB':
                for _dk in ('35BB', '50BB', '20BB'):
                    _ck = f'BBD_{_dk}_vs{opener_pos}'
                    _cr = _3b_ranges.get(_ck, {})
                    if _cr:
                        _chart_range = _cr
                        _chart_name = _ck
                        break
            if _chart_range:
                _n = len(_chart_range)
                _pct = round(_n / 169 * 100)
                # Show top hands from the chart
                _sorted = sorted(_chart_range.keys())[:8]
                _top = ', '.join(_sorted)
                _label = f'~{_pct}% defend (3-bet + flat)'
                note = (f"{hero_pos} vs {opener_pos} open: expected defend range is "
                        f"{_top}... ({_label})")
                return str(_chart_range), note
            # Fallback to hardcoded (approximate — no solver chart for this matchup)
            key = (hero_pos, opener_pos)
            if key not in _DEFEND_RANGES:
                return None, None
            range_str, label = _DEFEND_RANGES[key]
            note = (f"{hero_pos} vs {opener_pos} open: expected defend range is "
                    f"{range_str} ({label}) [approximate — no solver chart for this matchup]")
            return range_str, note

        # BUG-9 (Ron review 2026-05-31): the BB defend matrix was showing ALL
        # openers (UTG through SB) with a single 55-65% steal target, but the
        # aggregate "BB Defense vs Steal" overview row only counts CO/BTN/SB/HJ.
        # This caused: every per-segment row at-or-below target (because EP rows
        # are naturally tighter) yet the aggregate says over-defending (because
        # it only counts steal positions where defend rates are higher).
        # Fix: filter each matrix to the SAME position set as its aggregate,
        # use matching target band. Aggregate = weighted mean of segment rows.
        _STEAL_POS = {'CO', 'BTN', 'SB', 'HJ'}

        # Per-opener defend target map extracted from _DEFEND_RANGES labels.
        # Keyed by (hero_pos, opener_pos) → (tgt_lo, tgt_hi).
        # The label "~25% defend" → target band 20-30% (±5pp around midpoint).
        # Derive per-opener defend targets from chart widths when available
        _PER_OPENER_TARGETS = {}
        import re as _re_tgt
        # Dynamic: compute from SBD/BBD/BB_DEF chart sizes
        for _hp in ('SB', 'BB'):
            for _op in ('UTG', 'UTG+1', 'MP', 'HJ', 'CO', 'BTN', 'SB'):
                _widths = []
                if _hp == 'SB':
                    for _dk in ('20BB', '35BB', '50BB'):
                        _ck = f'SBD_{_dk}_vs{_op}'
                        _cr = _3b_ranges.get(_ck, {})
                        if _cr:
                            _widths.append(round(len(_cr) / 169 * 100))
                elif _hp == 'BB':
                    for _dk in ('20BB', '35BB', '50BB'):
                        _ck = f'BBD_{_dk}_vs{_op}'
                        _cr = _3b_ranges.get(_ck, {})
                        if _cr:
                            _widths.append(round(len(_cr) / 169 * 100))
                if _widths:
                    _mid = round(sum(_widths) / len(_widths))
                    _PER_OPENER_TARGETS[(_hp, _op)] = (max(0, _mid - 5), _mid + 5)
        # Fallback: fill from hardcoded _DEFEND_RANGES labels for any missing
        for (_hp, _op), (_rstr, _lbl) in _DEFEND_RANGES.items():
            if (_hp, _op) not in _PER_OPENER_TARGETS:
                _tm = _re_tgt.search(r'~(\d+)%', _lbl)
                if _tm:
                    _mid = int(_tm.group(1))
                    _PER_OPENER_TARGETS[(_hp, _op)] = (max(0, _mid - 5), _mid + 5)

        def _build_defend_matrix(hero_pos, tgt_lo, tgt_hi, label,
                                 allowed_openers=None):
            """Build per-opener defend matrix for hero_pos (SB or BB).
            tgt_lo/tgt_hi are the AGGREGATE targets for the header.
            Per-opener rows use position-specific targets from _PER_OPENER_TARGETS.
            allowed_openers: if set, only show these opener positions."""
            from collections import defaultdict
            by_opener = defaultdict(lambda: {'opps': 0, 'defend': 0,
                                               'fold_ids': [], 'wide_ids': []})
            for h in hands:
                if h.get('position') != hero_pos:
                    continue
                if not h.get('hero_faced_raise'):
                    continue
                op = h.get('opener_position', '?')
                # B-V10 (2026-06-01): removed LP-only filter for SB.
                # Show SB defense vs ALL opener positions, not just CO/BTN.
                if allowed_openers and op not in allowed_openers:
                    continue
                by_opener[op]['opps'] += 1
                if h.get('cold_called') or h.get('hero_3bet'):
                    by_opener[op]['defend'] += 1
                    # FEAT-5: track wide defends — hands where Hero defended
                    # with marginal holdings (bottom 20% of expected range)
                    # Heuristic: Hero called (not 3-bet) and lost > 10BB
                    if (h.get('cold_called') and not h.get('hero_3bet')
                            and (h.get('net_bb') or 0) < -10):
                        by_opener[op]['wide_ids'].append(h.get('id', ''))
                else:
                    # v8.5.3: range-gate missed defends using SBD/BBD/BB_DEF charts
                    # from Poker_Ranges_Text.txt instead of hardcoded _DEFEND_RANGES.
                    _should_defend = False
                    _hcards = h.get('cards', [])
                    if len(_hcards) >= 2:
                        from gem_analyzer import normalize_hand as _nh_def
                        _hn = _nh_def(_hcards)
                        if _hn:
                            _stk = h.get('eff_stack_bb') or h.get('stack_bb') or 30
                            if hero_pos == 'SB':
                                _dk = '20BB' if _stk <= 25 else ('35BB' if _stk <= 42 else '50BB')
                                _def_key = f'SBD_{_dk}_vs{op}'
                                _def_chart = _3b_ranges.get(_def_key, {})
                                if _def_chart and _hn in _def_chart:
                                    _should_defend = True
                            elif hero_pos == 'BB':
                                _opm_def = {'UTG': 15, 'UTG+1': 20, 'MP': 25,
                                            'HJ': 30, 'CO': 35, 'BTN': 45, 'SB': 50}
                                _opm_dyn = dict(_opm_def)
                                for _opp in _opm_def:
                                    _ows = [round(len(rv) / 169 * 100) for rk, rv in _3b_ranges.items()
                                            if rk.startswith('OPEN_') and rk.endswith(f'_{_opp}')]
                                    if _ows:
                                        _opm_dyn[_opp] = round(sum(_ows) / len(_ows))
                                _op_pct = _opm_dyn.get(op, 30)
                                _pct_opts = [15, 20, 25, 30, 35, 40, 45, 50]
                                _closest = min(_pct_opts, key=lambda x: abs(x - _op_pct))
                                _def_key = f'BB_DEF_vs{_closest}pct'
                                _def_chart = _3b_ranges.get(_def_key, {})
                                if _def_chart and _hn in _def_chart:
                                    _should_defend = True
                                # Also check BBD charts if available
                                if not _should_defend:
                                    _dk = '20BB' if _stk <= 25 else ('35BB' if _stk <= 42 else '50BB')
                                    _bbd_key = f'BBD_{_dk}_vs{op}'
                                    _bbd_chart = _3b_ranges.get(_bbd_key, {})
                                    if _bbd_chart and _hn in _bbd_chart:
                                        _should_defend = True
                            if not _should_defend:
                                # Fallback to hardcoded _DEFEND_RANGES
                                _dr_key = (hero_pos, op)
                                _dr_str = _DEFEND_RANGES.get(_dr_key, (None, None))[0]
                                if _dr_str and _hn[:2] in _dr_str:
                                    _should_defend = True
                    if _should_defend:
                        by_opener[op]['fold_ids'].append(h.get('id', ''))
            if not by_opener:
                return
            # BUG-9: compute weighted aggregate from segments
            _tot_def = sum(d['defend'] for d in by_opener.values())
            _tot_opps = sum(d['opps'] for d in by_opener.values())
            _agg_rate = (_tot_def / _tot_opps * 100) if _tot_opps else 0
            _agg_ci = _wilson_ci(_tot_def, _tot_opps)
            # v8.12.4 (QA items 1/3): the aggregate verdict compared the
            # all-opener defend rate against the STEAL-ONLY target band
            # (55-65%) even though most opportunities came from UTG-HJ opens
            # with 20-45% targets — a false red. Blend the per-opener targets
            # weighted by opportunity count so the aggregate is benchmarked
            # against what this exact opener mix actually demands.
            _w_lo = sum(_PER_OPENER_TARGETS.get((hero_pos, _op2), (tgt_lo, tgt_hi))[0]
                        * d2['opps'] for _op2, d2 in by_opener.items())
            _w_hi = sum(_PER_OPENER_TARGETS.get((hero_pos, _op2), (tgt_lo, tgt_hi))[1]
                        * d2['opps'] for _op2, d2 in by_opener.items())
            _agg_lo = round(_w_lo / _tot_opps) if _tot_opps else tgt_lo
            _agg_hi = round(_w_hi / _tot_opps) if _tot_opps else tgt_hi
            _agg_verdict = _verdict_ci(_tot_def, _tot_opps, _agg_lo, _agg_hi, n_min=10)
            doc.w(f"**{label} defend matrix** — per-opener breakdown "
                  f"(aggregate: {_agg_verdict} {_agg_rate:.0f}% "
                  f"[{_agg_ci[0]:.0f}-{_agg_ci[1]:.0f}%] vs {_agg_lo}-{_agg_hi}% "
                  f"opportunity-weighted target):")
            doc.w("")
            # FEAT-5: added "Wide Defends" column
            doc.w("| Vs Pos | Status | Defended | CI 90% | Target | Delta "
                  "| Missed | Wide |")
            doc.w("|---|:---:|---|---|---|---|---|---|")
            for op in sorted(by_opener, key=lambda x: _pos_rank.get(x, 9)):
                d = by_opener[op]
                if d['opps'] == 0:
                    continue
                n_def = d['defend']
                n_opps = d['opps']
                rate = n_def / n_opps * 100
                ci_lo, ci_hi = _wilson_ci(n_def, n_opps)
                # Use per-opener targets when available; fall back to aggregate
                _op_tgt = _PER_OPENER_TARGETS.get((hero_pos, op), (tgt_lo, tgt_hi))
                _row_tgt_lo, _row_tgt_hi = _op_tgt
                mid = (_row_tgt_lo + _row_tgt_hi) / 2
                delta = ((rate / mid - 1) * 100) if mid else 0
                verdict = _verdict_ci(n_def, n_opps, _row_tgt_lo, _row_tgt_hi, n_min=5)
                n_missed = len(d['fold_ids'])
                # Build linked pills for missed-defend hands
                _missed_refs = []
                for fid in d['fold_ids'][:5]:
                    fh = hands_by_id_local.get(fid)
                    if fh:
                        _missed_refs.append(_hand_ref(fh))
                # BUG-10: if there are missed defends, build as linked count
                if n_missed > 0 and d['fold_ids']:
                    _sel_ids = _popup_example_ids(d['fold_ids'], priority=1)  # P1: missed BB defends
                    _hids_str = ','.join(_sel_ids)
                    _m_title = _popup_title_with_count(
                        f"Missed {hero_pos} defends vs {op} ({n_missed})", len(d['fold_ids']))
                    missed_cell = (f'<a class="hand-list-trigger" href="#" '
                                  f'data-hids="{_hids_str}" '
                                  f'data-list-title="{_m_title}">'
                                  f'{n_missed}</a>')
                else:
                    missed_cell = str(n_missed)
                # FEAT-5: "Wide defends" column — linked count
                n_wide = len(d['wide_ids'])
                if n_wide > 0:
                    _w_sel = _popup_example_ids(d['wide_ids'], priority=1)  # P1: wide defends
                    _wide_hids = ','.join(_w_sel)
                    _w_title = _popup_title_with_count(
                        f"Wide {hero_pos} defends vs {op} ({n_wide})", len(d['wide_ids']))
                    wide_cell = (f'<a class="hand-list-trigger" href="#" '
                                f'data-hids="{_wide_hids}" '
                                f'data-list-title="{_w_title}">'
                                f'{n_wide}</a>')
                else:
                    wide_cell = '0'
                doc.w(f"| {op} | {verdict} | "
                      f"{rate:.0f}% ({n_def}/{n_opps}) | "
                      f"{ci_lo:.0f}-{ci_hi:.0f}% | {_row_tgt_lo}-{_row_tgt_hi}% | "
                      f"{delta:+.0f}% | {missed_cell.strip()} | {wide_cell} |")
            doc.w("")
            # v8.12.4 (QA item 3): when the SAME matrix shows meaningful
            # missed defends AND meaningful wide defends, that is one leak —
            # hand SELECTION — not two. Say it next to the data instead of
            # leaving the reader to reconcile two sections.
            _tot_missed_syn = sum(len(d['fold_ids']) for d in by_opener.values())
            _tot_wide_syn = sum(len(d['wide_ids']) for d in by_opener.values())
            if _tot_missed_syn >= 4 and _tot_wide_syn >= 4:
                doc.w(f"🧩 **Selection leak, not a frequency leak:** this matrix "
                      f"shows **{_tot_missed_syn} missed defends** (chart says "
                      f"continue, Hero folded) *and* **{_tot_wide_syn} wide "
                      f"defends** (continued with hands below the range) at the "
                      f"same time. The defend FREQUENCY can look acceptable "
                      f"while both lists grow — the fix is swapping the trash "
                      f"continues for the chart continues, not defending more "
                      f"or less overall. Cross-check the Out-of-Bound wide-"
                      f"defend bucket before drilling a raw frequency target.")
                doc.w("")
            # P1c FIX: show expected range note for EVERY opener position
            # (was latched to first only). Users need per-node context.
            for op in sorted(by_opener, key=lambda x: _pos_rank.get(x, 9)):
                _, _rn = _defend_range_note(hero_pos, op, None)
                if _rn:
                    doc.w(f"*Expected range — {_rn}*")
            doc.w("")

        # Show ALL opener positions for both SB and BB defense.
        # SB matrix: LP openers use 30-40% target; others shown for completeness.
        # BB matrix: steal positions use 55-65%; non-steal shown too.
        _build_defend_matrix('SB', 30, 40, 'SB defense')
        _build_defend_matrix('BB', 55, 65, 'BB defense')
    # BvB action distribution stays as its own table (different axis: action
    # shares not defense rate).
    bvb = s.get('sb_bvb_preflop', {})
    if bvb and bvb.get('total', 0) > 0:
        doc.w(f"**SB BvB (vs BB) — action distribution** "
              f"(depth {bvb.get('depth_bracket','—')}, "
              f"{bvb.get('total',0)} hands at depth):")
        doc.w("")
        doc.w("| Action | Count | Rate | CI 90% | Target (J29) |")
        doc.w("|---|---|---|---|---|")
        total = bvb.get('total', 0)
        for label, k_n, k_pct, tgt in [
            ('Limp', 'limp', 'limp_pct', '~80%'),
            ('Raise', 'raise', 'raise_pct', '~10%'),
            ('Fold', 'fold', 'fold_pct', '~10%'),
        ]:
            n = bvb.get(k_n, 0)
            pct = bvb.get(k_pct, 0)
            ci_lo, ci_hi = _wilson_ci(n, total)
            doc.w(f"| {label} | {n} | {pct:.1f}% | "
                  f"{ci_lo:.0f}-{ci_hi:.0f}% | {tgt} |")
        doc.w("")
        doc.w(f"*Target context (J29): {bvb.get('target','—')}*")
        doc.w("")

    # IV.8 Cold-Call Profile
    doc.subsection("sec-8-8", "S8.8 Cold-Call Profile",
                   "non-blind cold-call rate by position")
    _back_to_kpis(doc)
    # B-V11 FIX: hoist range imports to function-body scope — they are used
    # unconditionally at S8.4 (3-bet) and S8.6 (4-bet), not just inside S8.8.
    # Previously nested inside `if by_pos:` which crashed when cold_call_by_pos was empty.
    from collections import defaultdict as _ddict_iv4
    # B-V12: _nhc_3b, _hir_3b, _lr_3b, _3b_ranges all hoisted to function top (v8.5.5).

    by_pos = s.get('facing_action', {}).get('cold_call_by_pos', {})
    if by_pos:
        # Position-specific target bands for cold-call rate (Hero opens with calls
        # by position vs opener; tighter from EP, wider from later positions).
        _cc_targets = {'UTG+1': (3, 8), 'MP': (4, 10), 'HJ': (5, 12),
                       'CO': (6, 14), 'BTN': (8, 18)}
        # FEAT-6: added "Cold called" and "Missed CC" hand-list columns
        # Collect per-position hand IDs for cold-call vs missed cold-call
        _cc_hands_by_pos = {}
        _cc_missed_by_pos = {}
        for h in (hands or []):
            if not isinstance(h, dict):
                continue
            hpos = h.get('position', '')
            if hpos not in ('UTG+1', 'MP', 'HJ', 'CO', 'BTN'):
                continue
            if not h.get('hero_faced_raise'):
                continue
            hid = h.get('id', '')
            if h.get('cold_called'):
                _cc_hands_by_pos.setdefault(hpos, []).append(hid)
            elif h.get('vpip') is False and h.get('hero_faced_raise'):
                # BUG-M: only count as "missed CC" if the hand is in range.
                # J3o folding to a raise is correct, not a missed opportunity.
                if not h.get('hero_3bet') and not h.get('cold_called'):
                    # Range gate: check if hand is in the CC/defend range
                    _cc_cards = h.get('cards', [])
                    if len(_cc_cards) >= 2:
                        _cc_hclass = _nhc_3b(_cc_cards)
                        # Use open range as proxy (hands worth playing from this pos)
                        _cc_stack = h.get('eff_stack_bb_at_decision') or h.get('stack_bb') or 30
                        _cc_depth = '10-20BB' if _cc_stack <= 25 else '20-40BB' if _cc_stack <= 45 else '100BB'
                        _cc_range_key = f'OPEN_{_cc_depth}_{hpos}'
                        _cc_open_range = _3b_ranges.get(_cc_range_key) or {}
                        if not _cc_open_range:
                            try:
                                _cc_open_range = _lr_3b().get(_cc_range_key, {})
                            except Exception:
                                pass
                        if _cc_open_range and _cc_hclass and _cc_hclass in _cc_open_range:
                            _cc_missed_by_pos.setdefault(hpos, []).append(hid)
                        # If no range available, don't count (conservative)
                    # else: no cards → skip

        doc.w("| Status | Position | Rate | Target | CC/Opps "
              "| Cold called | Missed CC |")
        doc.w("|:---:|---|---|---|---|---|---|")
        for pos in ['UTG+1', 'MP', 'HJ', 'CO', 'BTN']:
            d = by_pos.get(pos, {})
            if d and d.get('opps', 0) > 0:
                opps = d.get('opps', 0)
                count = d.get('cc', d.get('count', 0))
                pct = d.get('pct', 0)
                tgt_lo, tgt_hi = _cc_targets.get(pos, (5, 12))
                status = _verdict_pct(pct, tgt_lo, tgt_hi, n=opps, n_min=15)
                # FEAT-6: linked count for cold-called hands
                _cc_ids = _cc_hands_by_pos.get(pos, [])
                if _cc_ids:
                    _cc_sel = _popup_example_ids(_cc_ids)
                    _cc_str = ','.join(_cc_sel)
                    _cc_title = _popup_title_with_count(
                        f"Cold calls from {pos} ({len(_cc_ids)})", len(_cc_ids))
                    cc_cell = (f'<a class="hand-list-trigger" href="#" '
                              f'data-hids="{_cc_str}" '
                              f'data-list-title="{_cc_title}">'
                              f'{len(_cc_ids)}</a>')
                else:
                    cc_cell = '0'
                # FEAT-6: linked count for missed cold-calls
                _missed_ids = _cc_missed_by_pos.get(pos, [])
                if _missed_ids:
                    _m_str = ','.join(_missed_ids[:10])
                    missed_cell = (f'<a class="hand-list-trigger" href="#" '
                                  f'data-hids="{_m_str}" '
                                  f'data-list-title="Missed CC from {pos} ({len(_missed_ids)})">'
                                  f'{len(_missed_ids)}</a>')
                else:
                    missed_cell = '0'
                doc.w(f"| {status} | {pos} | {pct:.1f}% | "
                      f"{tgt_lo}-{tgt_hi}% | {count}/{opps} | {cc_cell} | {missed_cell} |")
        _cc_nb_positions = ['UTG+1', 'MP', 'HJ', 'CO', 'BTN']
        _cc_tot_opps = sum(by_pos.get(p, {}).get('opps', 0) for p in _cc_nb_positions)
        _cc_tot_cc = sum(by_pos.get(p, {}).get('cc', by_pos.get(p, {}).get('count', 0)) for p in _cc_nb_positions)
        _cc_tot_pct = (100.0 * _cc_tot_cc / _cc_tot_opps) if _cc_tot_opps else 0
        if _cc_tot_opps:
            doc.w(f"| | **Total** | **{_cc_tot_pct:.1f}%** | | "
                  f"**{_cc_tot_cc}/{_cc_tot_opps}** | | |")
        doc.w("")

    # IV.4 3-Bet Profile
    # B-V10: collect 3-bet hand IDs by hero position and opener bucket
    # FEAT-A: also collect MISSED 3-bet hand IDs (should have 3-bet but didn't)
    # (imports hoisted above FEAT-6 block — B-V11)
    _3b_ids_by_hero_pos = _ddict_iv4(list)
    _3b_ids_by_opener = _ddict_iv4(list)
    _missed_3b_by_hero_pos = _ddict_iv4(list)
    _EP = {'UTG', 'UTG+1', 'UTG+2', 'EP'}
    _MP = {'MP', 'LJ', 'HJ'}
    _LP = {'CO', 'BTN'}
    _BL = {'SB', 'BB'}
    # _3b_ranges already hoisted to function-body scope (B-V12)
    for h in hands:
        if h.get('hero_3bet') and h.get('id'):
            _3b_ids_by_hero_pos[h.get('position', '?')].append(h['id'])
            _op = h.get('opener_position', '?')
            if _op in _EP: _3b_ids_by_opener['EP'].append(h['id'])
            elif _op in _MP: _3b_ids_by_opener['MP'].append(h['id'])
            elif _op in _LP: _3b_ids_by_opener['LP'].append(h['id'])
            elif _op in _BL: _3b_ids_by_opener['Blinds'].append(h['id'])
        # FEAT-A: detect missed 3-bets (hero faced a raise, didn't 3-bet, but hand is in range)
        elif (h.get('hero_faced_raise') and not h.get('hero_3bet')
              and h.get('id') and h.get('cards') and len(h.get('cards', [])) >= 2):
            _hpos = h.get('position', '?')
            _opos = h.get('opener_position', '?')
            _stack = h.get('eff_stack_bb_at_decision') or h.get('stack_bb') or 0
            _hclass = _nhc_3b(h['cards'])
            if _hclass:
                # Find matching 3-bet range by depth + position pair
                _depth_tier = '20BB' if _stack <= 25 else '30BB' if _stack <= 40 else '50BB'
                _range_key = f'3BET_{_depth_tier}_{_hpos}vs{_opos}'
                _range = _3b_ranges.get(_range_key, {})
                if _range and _hclass in _range:
                    _missed_3b_by_hero_pos[_hpos].append(h['id'])
    doc.subsection("sec-8-4", "S8.4 3-Bet Profile",
                   "by opener position + by hero position")
    _back_to_kpis(doc)
    by_op = s.get('threebet_by_opener', {})
    by_hero = s.get('threebet_by_hero_pos', {})
    # B-status (Ron 2026-05-11): standard 3-bet target bands for status dots
    # vs EP: 6-9%; vs MP: 7-10%; vs LP: 9-13%; vs Blinds: 5-9%
    _3b_targets = {'EP': (6, 9), 'MP': (7, 10), 'LP': (9, 13), 'Blinds': (5, 9)}
    # Phase 4.8: merged By Opener + By Hero into one table with grouped View col
    if by_op or by_hero:
        doc.w("| View | Position | Status | Rate | Target | 3-Bets | Missed | Opps |")
        doc.w("|---|---|:---:|---|---|---|---|---|")
        # Item 10: group first column — show group label once, blank on continuation
        # FEAT-7: add total rows to both views
        if by_op:
            _first_op = True
            _tot_op_3b, _tot_op_opps = 0, 0
            for k in ['EP', 'MP', 'LP', 'Blinds']:
                d = by_op.get(k, {})
                if d:
                    opps = d.get('opps', 0)
                    count = d.get('3bets', d.get('count', 0))
                    rate = d.get('rate', 0)
                    tgt_lo, tgt_hi = _3b_targets[k]
                    status = _verdict_pct(rate, tgt_lo, tgt_hi, n=opps, n_min=20)
                    _view = "By Opener Position" if _first_op else ""
                    _op_pool = _3b_ids_by_opener.get(k, [])
                    _op_ids = _popup_example_ids(_op_pool)
                    if _op_ids:
                        _op_str = ','.join(_op_ids)
                        _op_title = _popup_title_with_count(f"3-Bets vs {k} ({count})", len(_op_pool))
                        _cnt_cell = (f'<a class="hand-list-trigger" href="#" '
                                     f'data-hids="{_op_str}" '
                                     f'data-list-title="{_op_title}">'
                                     f'{count}</a>')
                    else:
                        _cnt_cell = str(count)
                    doc.w(f"| {_view} | vs {k} | {status} | "
                          f"{rate:.1f}% | {tgt_lo}-{tgt_hi}% | {_cnt_cell} | | {opps} |")
                    _first_op = False
                    _tot_op_3b += count; _tot_op_opps += opps
            if _tot_op_opps:
                _tot_rate = _tot_op_3b / _tot_op_opps * 100
                doc.w(f"| | **Total** | | **{_tot_rate:.1f}%** | | "
                      f"**{_tot_op_3b}** | | **{_tot_op_opps}** |")
        if by_hero:
            _first_hero = True
            _tot_h_3b, _tot_h_opps = 0, 0
            for pos in ['UTG+1', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB']:
                d = by_hero.get(pos, {})
                if d:
                    opps = d.get('opps', 0)
                    count = d.get('3bets', d.get('count', 0))
                    rate = d.get('rate', 0)
                    status = _verdict_pct(rate, 6, 12, n=opps, n_min=20)
                    _view = "By Hero Position" if _first_hero else ""
                    _hp_pool = _3b_ids_by_hero_pos.get(pos, [])
                    _hp_ids = _popup_example_ids(_hp_pool)
                    if _hp_ids:
                        _hp_str = ','.join(_hp_ids)
                        _hp_title = _popup_title_with_count(f"3-Bets from {pos} ({count})", len(_hp_pool))
                        _hcnt_cell = (f'<a class="hand-list-trigger" href="#" '
                                      f'data-hids="{_hp_str}" '
                                      f'data-list-title="{_hp_title}">'
                                      f'{count}</a>')
                    else:
                        _hcnt_cell = str(count)
                    # FEAT-A: Missed 3-bets — use teaching examples when available
                    _te_3b = (s.get('teaching_examples') or {}).get('missed_3bet', {})
                    _te_3b_ids = _te_3b.get('teaching_example_ids', [])
                    _m3b_pool = _missed_3b_by_hero_pos.get(pos, [])
                    # Filter teaching example IDs to this position
                    _m3b_te = [hid for hid in _te_3b_ids if hid in set(_m3b_pool)] if _te_3b_ids else []
                    _n_missed_3b = len(_m3b_pool)
                    _display_ids = _m3b_te if _m3b_te else _m3b_pool
                    if _display_ids:
                        _m3b_sel = _popup_example_ids(_display_ids, priority=0)  # P0: missed 3-bet teaching
                        _m3b_str = ','.join(_m3b_sel)
                        _m3b_label = (f'{len(_m3b_te)} clear from {_n_missed_3b} missed'
                                      if _m3b_te and len(_m3b_te) < _n_missed_3b
                                      else f'Missed 3-bets from {pos} ({_n_missed_3b})')
                        _m3b_title = _popup_title_with_count(_m3b_label, len(_display_ids))
                        _m3b_cell = (f'<a class="hand-list-trigger" href="#" '
                                    f'data-hids="{_m3b_str}" '
                                    f'data-list-title="{_m3b_title}">'
                                    f'{_n_missed_3b}</a>')
                    else:
                        _m3b_cell = '0'
                    doc.w(f"| {_view} | {pos} | {status} | "
                          f"{rate:.1f}% | 6-12% | {_hcnt_cell} | {_m3b_cell} | {opps} |")
                    _first_hero = False
                    _tot_h_3b += count; _tot_h_opps += opps
            _tot_missed_3b = sum(len(v) for v in _missed_3b_by_hero_pos.values())
            if _tot_h_opps:
                _tot_rate = _tot_h_3b / _tot_h_opps * 100
                doc.w(f"| | **Total** | | **{_tot_rate:.1f}%** | | "
                      f"**{_tot_h_3b}** | **{_tot_missed_3b}** | **{_tot_h_opps}** |")
        doc.w("")
    # 3-Bet Sizing by Depth (Dave J44)
    j44 = s.get('ip_3bet_sizing', {})
    buckets = j44.get('buckets', {})
    if buckets:
        doc.w("**IP 3-Bet Sizing by Depth (Dave J44):**")
        doc.w("")
        doc.w("| Depth | Hands | Mean Sizing | Target | Deviations |")
        doc.w("|---|---|---|---|---|")
        for k in ['<25BB', '25-40BB', '40+BB']:
            v = buckets.get(k, {})
            mean = v.get('mean_size_x')
            mean_str = f"{mean:.2f}x" if mean else "—"
            target = v.get('target', '—')
            target_str = f"{target}x" if target else "—"
            # FEAT-7: deviation count links to hand list
            devs = v.get('deviations', [])
            n_dev = len(devs)
            if n_dev > 0:
                _dev_pool = [d.get('id', '') for d in devs
                             if isinstance(d, dict) and d.get('id')]
                _dev_sel = _popup_example_ids(_dev_pool, priority=0)  # P0: J44 sizing deviations
                _dev_hids = ','.join(_dev_sel)
                if _dev_hids:
                    _dev_title = _popup_title_with_count(
                        f"J44 sizing deviations {k} ({n_dev})", len(_dev_pool))
                    dev_cell = (f'<a class="hand-list-trigger" href="#" '
                               f'data-hids="{_dev_hids}" '
                               f'data-list-title="{_dev_title}">'
                               f'{n_dev}</a>')
                else:
                    dev_cell = str(n_dev)
            else:
                dev_cell = '0'
            doc.w(f"| {k} | {v.get('count',0)} | {mean_str} | {target_str} | "
                  f"{dev_cell} |")
        doc.w("")

    # IV.4.5 Preflop Aggression Matrix (D4 Ron 2026-05-11)
    # One-row-per-position view combining 3-bet, squeeze, and 4-bet rates
    # so Ron can skim "where am I tight/loose" without flipping through
    # IV.4 / IV.5 / IV.6 individually. Statuses use _verdict_pct so each
    # cell gets 🟢/🟡/🔴/⚪ based on its own target band + sample size.
    # Phase 4.8: removed IV4.5 numbering per review
    doc.w("**Preflop Aggression Matrix by Position:**")
    doc.w("")
    by_hero_3b = s.get('threebet_by_hero_pos', {})
    h4b_by_pos_matrix = core.get('hero_4bet_by_pos', {})
    # squeeze-by-pos computed from hands
    from collections import defaultdict as _dd
    sq_by_pos = _dd(lambda: {'opps': 0, 'sq': 0})
    for h in hands:
        if h.get('squeeze_opp'):
            sq_by_pos[h.get('position','?')]['opps'] += 1
            if h.get('is_squeeze'):
                sq_by_pos[h.get('position','?')]['sq'] += 1
    doc.w("| Pos | 3-Bet (target 6-12%) | Status | Squeeze (target 6-12%) | Status | 4-Bet (target 5-12%) | Status |")
    doc.w("|---|---|---|---|---|---|---|")
    for pos in ['UTG', 'UTG+1', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB']:
        # 3-bet cell
        d3 = by_hero_3b.get(pos, {})
        opps_3 = d3.get('opps', 0)
        rate_3 = d3.get('rate', 0) if opps_3 else None
        if opps_3 >= 15:
            stat_3 = _verdict_pct(rate_3, 6, 12, n=opps_3, n_min=15)
            cell_3 = f"{rate_3:.1f}% (n={opps_3})"
        elif opps_3 > 0:
            stat_3 = '⚪'
            cell_3 = f"{rate_3:.1f}% (n={opps_3})"
        else:
            stat_3, cell_3 = '⚪', '—'
        # Squeeze cell
        ds = sq_by_pos.get(pos, {})
        opps_s = ds.get('opps', 0)
        rate_s = (100.0 * ds['sq'] / opps_s) if opps_s else 0
        if opps_s >= 10:
            stat_s = _verdict_pct(rate_s, 6, 12, n=opps_s, n_min=10)
            cell_s = f"{rate_s:.1f}% (n={opps_s})"
        elif opps_s > 0:
            stat_s, cell_s = '⚪', f"{rate_s:.1f}% (n={opps_s})"
        else:
            stat_s, cell_s = '⚪', '—'
        # 4-bet cell
        d4 = h4b_by_pos_matrix.get(pos, {})
        opps_4 = d4.get('opps', 0)
        rate_4 = d4.get('pct', 0) if opps_4 else None
        if opps_4 >= 10:
            stat_4 = _verdict_pct(rate_4, 5, 12, n=opps_4, n_min=10)
            cell_4 = f"{rate_4:.1f}% (n={opps_4})"
        elif opps_4 > 0:
            stat_4, cell_4 = '⚪', f"{rate_4:.1f}% (n={opps_4})"
        else:
            stat_4, cell_4 = '⚪', '—'
        # Skip rows with no data anywhere
        if cell_3 == '—' and cell_s == '—' and cell_4 == '—':
            continue
        doc.w(f"| {pos} | {cell_3} | {stat_3} | {cell_s} | {stat_s} | {cell_4} | {stat_4} |")
    doc.w("")

    # IV.5 Squeeze (count Hero squeezes from hands directly)
    doc.subsection("sec-8-5", "S8.5 Squeeze Frequency",
                   "Hero squeeze rate when PFR + caller present")
    _sq_ids = [h['id'] for h in hands if h.get('is_squeeze') and h.get('id')]
    sq_opps = sum(1 for h in hands if h.get('squeeze_opp'))
    sq_did = len(_sq_ids)
    if sq_opps > 0:
        sq_pct = 100.0 * sq_did / sq_opps
        ci_lo, ci_hi = _wilson_ci(sq_did, sq_opps)
        verdict = _verdict_ci(sq_did, sq_opps, 6, 12, n_min=10)
        if _sq_ids:
            _sq_sel = _popup_example_ids(_sq_ids)
            _sq_str = ','.join(_sq_sel)
            _sq_title = _popup_title_with_count(f"Hero Squeezes ({sq_did})", len(_sq_ids))
            _sq_cell = (f'<a class="hand-list-trigger" href="#" '
                        f'data-hids="{_sq_str}" '
                        f'data-list-title="{_sq_title}">'
                        f'{sq_did}/{sq_opps}</a>')
        else:
            _sq_cell = f'{sq_did}/{sq_opps}'
        doc.w("<<ANCHOR:tbl-squeeze-frequency>>")
        # Missed squeeze — teaching examples
        _te_sq = (s.get('teaching_examples') or {}).get('missed_squeeze', {})
        _msq_ids = (_te_sq.get('teaching_example_ids')
                    or (s.get('popup_hand_ids') or {}).get('missed_squeeze_ids', []))
        _msq_total = _te_sq.get('total_opps', sq_opps - sq_did)
        _msq_qual = _te_sq.get('qualified_n', len(_msq_ids))
        _msq_n = sq_opps - sq_did
        _msq_cell = ''
        if _msq_ids and _msq_n > 0:
            _msq_sel = _popup_example_ids(_msq_ids, priority=0)  # P0: missed squeeze teaching
            _msq_str = ','.join(_msq_sel)
            _msq_mixed = _te_sq.get('mixed_n', 0)
            _msq_label = (f'{_msq_qual} clear examples from {_msq_total} opportunities'
                          + (f' ({_msq_mixed} borderline)' if _msq_mixed else '')
                          if _msq_qual < _msq_total
                          else f'Missed squeezes ({_msq_n})')
            _msq_cell = (f' <a class="hand-list-trigger" href="#" '
                        f'data-hids="{_msq_str}" '
                        f'data-list-title="{_msq_label}">'
                        f'{_msq_n} missed</a>')
        # Single merged table: total row + per-position breakdown
        from collections import defaultdict
        by_pos = defaultdict(lambda: {'opps': 0, 'sq': 0, 'ids': [], 'missed_ids': []})
        for h in hands:
            if h.get('squeeze_opp'):
                pos = h.get('position', '?')
                by_pos[pos]['opps'] += 1
                if h.get('is_squeeze'):
                    by_pos[pos]['sq'] += 1
                    if h.get('id'):
                        by_pos[pos]['ids'].append(h['id'])
                elif h.get('id'):
                    by_pos[pos]['missed_ids'].append(h['id'])
        doc.w("| Status | Position | Rate | Target | Squeezes/Opps | Missed |")
        doc.w("|:---:|---|---|---|---|---|")
        doc.w(f"| {verdict} | **Total** | **{sq_pct:.1f}%** | 6-12% | "
              f"**{_sq_cell}** | {_msq_cell} |")
        for pos in ['UTG', 'UTG+1', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB']:
            d = by_pos.get(pos, {})
            if d.get('opps', 0) > 0:
                opps = d['opps']
                n = d['sq']
                pct = 100.0 * n / opps
                status = _verdict_pct(pct, 6, 12, n=opps, n_min=10)
                _sp_pool = d.get('ids', [])
                _sp_ids = _popup_example_ids(_sp_pool)
                if _sp_ids:
                    _sp_str = ','.join(_sp_ids)
                    _sp_title = _popup_title_with_count(f"Squeezes from {pos} ({n})", len(_sp_pool))
                    _sp_cell = (f'<a class="hand-list-trigger" href="#" '
                                f'data-hids="{_sp_str}" '
                                f'data-list-title="{_sp_title}">'
                                f'{n}/{opps}</a>')
                else:
                    _sp_cell = f'{n}/{opps}'
                # Missed squeeze per position
                _ms_pool = d.get('missed_ids', [])
                if _ms_pool:
                    _ms_sel = _popup_example_ids(_ms_pool, priority=1)  # P1: missed squeeze per pos
                    _ms_str = ','.join(_ms_sel)
                    _ms_title = f"Missed squeezes from {pos} ({len(_ms_pool)})"
                    _ms_cell = (f'<a class="hand-list-trigger" href="#" '
                               f'data-hids="{_ms_str}" '
                               f'data-list-title="{_ms_title}">'
                               f'{len(_ms_pool)}</a>')
                else:
                    _ms_cell = '0'
                doc.w(f"| {status} | {pos} | {pct:.1f}% | "
                      f"6-12% | {_sp_cell} | {_ms_cell} |")
        doc.w("")
    else:
        doc.w("⚪ No squeeze opportunities flagged this session.")
        doc.w("")

    # IV.6 Hero 4-Bet (by position)
    doc.subsection("sec-8-6", "S8.6 Hero 4-Bet by Position",
                   "Hero opened, faced 3-bet, 4-bet response")
    _back_to_kpis(doc)
    doc.w("<<ANCHOR:tbl-4bet-frequency>>")
    h4b_overall_n = core.get('hero_4bet_when_facing_3bet_n', 0)
    h4b_overall_pct = core.get('hero_4bet_when_facing_3bet_pct', 0)
    if h4b_overall_n > 0:
        ci_lo, ci_hi = _wilson_ci(round(h4b_overall_pct * h4b_overall_n / 100), h4b_overall_n)
        # v7.43 (Ron 2026-05-09): target updated 12-20% → 5-12%. Old target
        # was IP-aggressor deep-stack range; MTT 25-50BB depths run lower
        # 4-bet frequencies because shorter SPR makes flatting more attractive
        # vs a 3-bet, and pure 4-bet bluffs are harder to balance with thinner
        # value combos at depth.
        verdict = _verdict_pct(h4b_overall_pct, 5, 12, n=h4b_overall_n, n_min=10)
        doc.w(f"**Overall:** {h4b_overall_pct:.1f}% (n={h4b_overall_n}, "
              f"CI {ci_lo:.0f}-{ci_hi:.0f}%) | target 5-12% | {verdict}")
        doc.w("")
    h4b_by_pos = core.get('hero_4bet_by_pos', {})
    # B-V10: collect 4-bet hand IDs by position
    # FEAT-B: also collect MISSED 4-bet IDs (should have 4-bet but didn't)
    _4b_ids_by_pos = _ddict_iv4(list)
    _missed_4b_by_pos = _ddict_iv4(list)
    # Load 4-bet ranges
    _4b_ranges = {k: v for k, v in (_lr_3b() or {}).items() if k.startswith('4BET_')}
    for h in hands:
        if (h.get('hero_4bet_only') or h.get('hero_5bet_plus')) and h.get('id'):
            _4b_ids_by_pos[h.get('position', '?')].append(h['id'])
        # FEAT-B: detect missed 4-bets
        elif (h.get('hero_called_3bet') and not h.get('hero_4bet_only')
              and h.get('id') and h.get('cards') and len(h.get('cards', [])) >= 2):
            _hpos4 = h.get('position', '?')
            _3bettor = h.get('opener_position', '?')  # who 3-bet us
            _stack4 = h.get('eff_stack_bb_at_decision') or h.get('stack_bb') or 0
            _hclass4 = _nhc_3b(h['cards'])
            if _hclass4:
                _depth4 = '30BB' if _stack4 <= 40 else '50BB'
                _rk4 = f'4BET_{_depth4}_{_hpos4}vs{_3bettor}3B'
                _range4 = _4b_ranges.get(_rk4, {})
                if _range4 and _hclass4 in _range4:
                    _missed_4b_by_pos[_hpos4].append(h['id'])
    if h4b_by_pos:
        doc.w("| Status | Position | Rate | Target | 4-Bets/Opps | Missed |")
        doc.w("|:---:|---|---|---|---|---|")
        for pos in ['UTG', 'UTG+1', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB']:
            d = h4b_by_pos.get(pos, {})
            if d and d.get('opps', 0) > 0:
                opps = d.get('opps', 0)
                count = d.get('count', 0)
                pct = d.get('pct', 0)
                status = _verdict_pct(pct, 5, 12, n=opps, n_min=10)
                _4b_pool = _4b_ids_by_pos.get(pos, [])
                _4b_ids = _popup_example_ids(_4b_pool)
                if _4b_ids:
                    _4b_str = ','.join(_4b_ids)
                    _4b_title = _popup_title_with_count(f"4-Bets from {pos} ({count})", len(_4b_pool))
                    _4b_cell = (f'<a class="hand-list-trigger" href="#" '
                                f'data-hids="{_4b_str}" '
                                f'data-list-title="{_4b_title}">'
                                f'{count}/{opps}</a>')
                else:
                    _4b_cell = f'{count}/{opps}'
                # FEAT-B: Missed 4-bets column
                _m4b_pool = _missed_4b_by_pos.get(pos, [])
                if _m4b_pool:
                    _m4b_sel = _popup_example_ids(_m4b_pool, priority=1)  # P1: missed 4-bets
                    _m4b_str = ','.join(_m4b_sel)
                    _m4b_title = _popup_title_with_count(
                        f"Missed 4-bets from {pos} ({len(_m4b_pool)})", len(_m4b_pool))
                    _m4b_cell = (f'<a class="hand-list-trigger" href="#" '
                                f'data-hids="{_m4b_str}" '
                                f'data-list-title="{_m4b_title}">'
                                f'{len(_m4b_pool)}</a>')
                else:
                    _m4b_cell = '0'
                doc.w(f"| {status} | {pos} | {pct:.1f}% | "
                      f"5-12% | {_4b_cell} | {_m4b_cell} |")
        # Total row
        doc.w(f"| {_verdict_pct(h4b_overall_pct, 5, 12, n=h4b_overall_n, n_min=10)} | "
              f"**Total** | **{h4b_overall_pct:.1f}%** | 5-12% | | |")
        doc.w("")

    # IV.7 Hero 5-Bet+ — bug fixed v7.43 (B47): CSV now emits hero_5bet_when_faced_5bet_pct
    doc.subsection("sec-8-7", "S8.7 Hero 5-Bet+",
                   "5-bet response rate when Hero 4-bet then faced a 5-bet")
    _back_to_kpis(doc)
    h5_proper_n = core.get('hero_5bet_when_faced_5bet_n', 0)
    h5_proper = core.get('hero_5bet_when_faced_5bet_pct', 0)
    if h5_proper_n == 0:
        doc.w("Hero never faced a 5-bet this session — sample insufficient. ⚪")
        doc.w("")
    else:
        ci_lo, ci_hi = _wilson_ci(round(h5_proper * h5_proper_n / 100), h5_proper_n)
        verdict = _verdict_pct(h5_proper, 15, 25, n=h5_proper_n, n_min=10)
        doc.w(f"**Hero 5-Bet response rate:** {h5_proper:.1f}% (n={h5_proper_n}, "
              f"CI {ci_lo:.0f}-{ci_hi:.0f}%) | target 15-25% | {verdict}")
        doc.w("")
        doc.w("*Stat fixed v7.43 (B47): CSV `Hero_5Bet` column now emits "
              "`hero_5bet_when_faced_5bet_pct` (correct denom: of times Hero 4-bet "
              "and faced a 5-bet, what % did Hero 5-bet+). Was previously "
              "`hero_5bet_legacy_pct` (5-bet count / facing-3-bet count = wrong denom).*")
        doc.w("")

    # Phase 4.8: Steal Defense moved here from S11 per review (end of preflop)
    _emit_steal_defense(doc, s, rd, hands)


def _emit_steal_defense(doc, s, rd, hands):
    """S11.9 Steal Defense / Re-Steal — moved to end of preflop (Phase 4.8)."""
    fa = s.get('facing_action', {})
    doc.subsection("sec-11-9", "S11.9 Steal Defense / Re-Steal",
                   "BB face-steal + Hero re-steal frequency")
    _back_to_kpis(doc)
    steals = fa.get('steals', {})
    if steals:
        bb_opps = steals.get('bb_face_opps', 0)
        bb_fold = steals.get('fold_to_steal', 0)
        bb_fold_pct = steals.get('fold_to_steal_pct', 0)
        rs_opps = steals.get('restole_opps', 0)
        rs_n = steals.get('restole', 0)
        rs_pct = steals.get('restole_pct', 0)
        # B229 (Ron 2026-06-01): collect hand IDs for clickable drill-down.
        # fold-to-steal = BB faced a steal and folded (the leak when red).
        # faced-steal   = BB faced a steal (full opportunity set for context).
        # restole       = Hero re-stole (3bet a steal attempt).
        _fold_ids = [h['id'] for h in hands
                     if h.get('fold_to_steal_bb') and h.get('id')]
        _faced_ids = [h['id'] for h in hands
                      if h.get('faced_steal_bb') and h.get('id')]
        _rs_ids = [h['id'] for h in hands
                   if h.get('restole') and h.get('id')]
        doc.w("| Stat | Count | Rate | Target | Status |")
        doc.w("|---|---|---|---|---|")
        if bb_opps > 0:
            v = _verdict_ci(bb_fold, bb_opps, 35, 45, n_min=10)
            # Clickable stat name linking to fold-to-steal hand list
            if _fold_ids:
                _hids_str = ','.join(_fold_ids[:50])
                _stat_cell = (f'<a class="hand-list-trigger" href="#" '
                              f'data-hids="{_hids_str}" '
                              f'data-list-title="BB Fold-to-Steal ({len(_fold_ids)} hands)">'
                              f'BB Fold-to-Steal</a>')
            else:
                _stat_cell = 'BB Fold-to-Steal'
            doc.w(f"| {_stat_cell} | {bb_fold}/{bb_opps} | {bb_fold_pct:.1f}% "
                  f"| 35-45% | {v} |")
        if rs_opps > 0:
            v = _verdict_ci(rs_n, rs_opps, 7, 14, n_min=10)
            if _rs_ids:
                _rs_str = ','.join(_rs_ids[:50])
                _stat_cell = (f'<a class="hand-list-trigger" href="#" '
                              f'data-hids="{_rs_str}" '
                              f'data-list-title="Hero Re-Steal ({len(_rs_ids)} hands)">'
                              f'Hero Re-Steal</a>')
            else:
                _stat_cell = 'Hero Re-Steal'
            doc.w(f"| {_stat_cell} | {rs_n}/{rs_opps} | {rs_pct:.1f}% "
                  f"| 7-14% | {v} |")
        doc.w("")


# ============================================================
# SECTION V — POST-FLOP SRP
# ============================================================

def _emit_section_v(doc, s, rd, hands):
    cb = s.get('cbet', {})
    hu_ip_n = cb.get('hu_ip_opp', 0)
    hu_ip_pct = cb.get('hu_ip_pct', 0)
    # B-status (Ron 2026-05-11): V section header summary — auto-status from
    # HU IP cbet rate vs target 60-75% so reader knows whether to dive in.
    if hu_ip_n >= 10:
        v_status = _verdict_pct(hu_ip_pct, 60, 75, n=hu_ip_n, n_min=10)
    else:
        v_status = '⚪ (insufficient sample)'
    doc.section("sec-9", "S9. Post-Flop SRP",
                f"HU IP cbet {hu_ip_pct:.1f}% (n={hu_ip_n}) {v_status}")
    # Synthesize key findings line for skim-reading: which subsections are
    # in/out of target.
    summary_bits = []
    if hu_ip_n >= 10:
        if 60 <= hu_ip_pct <= 75: summary_bits.append(f"HU IP cbet 🟢 {hu_ip_pct:.0f}%")
        elif hu_ip_pct > 75: summary_bits.append(f"HU IP cbet 🟡 too high ({hu_ip_pct:.0f}%, target 60-75%)")
        else: summary_bits.append(f"HU IP cbet 🟡 low ({hu_ip_pct:.0f}%, target 60-75%)")
    mw_n = cb.get('mw_opp', 0); mw_pct = cb.get('mw_pct', 0)
    if mw_n >= 10:
        if 30 <= mw_pct <= 45: summary_bits.append(f"MW cbet 🟢 {mw_pct:.0f}%")
        elif mw_pct > 45: summary_bits.append(f"MW cbet 🔴 over-betting MW ({mw_pct:.0f}%, target 30-45%)")
        else: summary_bits.append(f"MW cbet 🟡 under-betting ({mw_pct:.0f}%)")
    if summary_bits:
        doc.w(f"**Skim-line:** {' · '.join(summary_bits)}")
        doc.w("")

    # V.1 As Aggressor IP
    doc.subsection("sec-9-1", "S9.1 As Aggressor IP",
                   "cbet split + by-position + texture + GTO compliance")
    doc.w("<<ANCHOR:tbl-cbet-split>>")
    doc.w("**C-Bet Split (samples + Wilson CI):**")
    doc.w("")
    doc.write_block(metric_table_block("t3-cbet-split", [
        {"name": "HU IP", "x": cb.get('hu_ip_bet', 0),
         "n": cb.get('hu_ip_opp', 0), "target_lo": 60, "target_hi": 75,
         "notes": "in-position, heads-up SRP cbet"},
        {"name": "HU OOP", "x": cb.get('hu_oop_bet', 0),
         "n": cb.get('hu_oop_opp', 0), "target_lo": 35, "target_hi": 55,
         "notes": "out-of-position SRP cbet"},
        {"name": "MW (multiway)", "x": cb.get('mw_bet', 0),
         "n": cb.get('mw_opp', 0), "target_lo": 30, "target_hi": 45,
         "notes": "3+ players to flop"},
        {"name": "Turn (double-barrel)", "x": cb.get('turn_bet', 0),
         "n": cb.get('turn_opp', 0), "target_lo": 50, "target_hi": 65,
         "notes": "after flop cbet, turn bet"},
        {"name": "River (triple-barrel)", "x": cb.get('river_bet', 0),
         "n": cb.get('river_opp', 0), "target_lo": 35, "target_hi": 55,
         "notes": "after turn cbet, river bet"},
    ]))
    doc.w("")

    # Drill-down: barrel/probe/3BP c-bet hand lists from popup_hand_ids
    _phids = s.get('popup_hand_ids', {})
    _drill_lines = []
    for _dk, _dlabel in [
        ('double_barrel_ids', 'Double barrels'),
        ('missed_barrel_ids', 'Missed turn barrels'),
        ('triple_barrel_ids', 'Triple barrels'),
        ('missed_triple_ids', 'Gave up river after barreling'),
        ('probe_turn_ids', 'Turn probes'),
        ('missed_probe_ids', 'Missed turn probes'),
        ('cbet_3bp_ids', 'C-bets in 3BP'),
        ('missed_cbet_3bp_ids', 'Missed c-bets in 3BP'),
        ('missed_river_value_ids', 'Missed river value bets'),
        ('missed_bluff_river_ids', 'Checked back river with air'),
        ('bet_fold_flop_ids', 'Bet-fold on flop'),
        ('bet_fold_turn_ids', 'Bet-fold on turn'),
        ('missed_cr_flop_ids', 'Missed check-raise (strong hand called)'),
    ]:
        _dids = _phids.get(_dk, [])
        if _dids:
            _dsel = _popup_example_ids(_dids, priority=1)  # P1: postflop drill hands
            _dstr = ','.join(_dsel)
            _dtitle = _popup_title_with_count(f"{_dlabel} ({len(_dids)})", len(_dids))
            _drill_lines.append(
                f'<a class="hand-list-trigger" href="#" '
                f'data-hids="{_dstr}" data-list-title="{_dtitle}">'
                f'{_dlabel} ({len(_dids)})</a>')
    if _drill_lines:
        doc.w("**Postflop action drill-down** (click to see hands):")
        doc.w("")
        for _dl in _drill_lines:
            doc.w(f"- {_dl}")
        doc.w("")

    # Batch 4 (ACE-1): C-bet by Board Texture matrix
    _cbt = s.get('cbet_by_texture', {})
    if _cbt:
        # Population targets by texture class (rough heuristics)
        _tex_targets = {
            'dry_ahigh': (55, 75), 'dry_khigh': (50, 70), 'dry_low': (40, 60),
            'paired_board': (45, 65), 'monotone': (25, 45),
            'connected_mid': (25, 40), 'connected_high': (30, 50),
            'wet_draw_heavy': (30, 50), 'unknown': (40, 60),
        }
        doc.w(f"**C-Bet by Board Texture:**{_new_badge('cbet_by_texture')}")
        doc.w("")
        doc.w("| Texture | C-bet% | Target | Opps | C-bets | Missed |")
        doc.w("|---|---|---|---|---|---|")
        for tex in sorted(_cbt.keys()):
            v = _cbt[tex]
            _tgt = _tex_targets.get(tex, (35, 60))
            _verdict = _verdict_ci(v['cbet'], v['opps'], _tgt[0], _tgt[1], n_min=5)
            _tex_label = tex.replace('_', ' ').title()
            # Clickable c-bet count
            _cb_ids = _popup_example_ids(v.get('ids_cbet', []))
            if _cb_ids:
                _cb_str = ','.join(_cb_ids)
                _cb_title = _popup_title_with_count(f"C-bets on {_tex_label} ({v['cbet']})",
                                                     len(v.get('ids_cbet', [])))
                _cb_cell = (f'<a class="hand-list-trigger" href="#" '
                           f'data-hids="{_cb_str}" data-list-title="{_cb_title}">'
                           f'{v["cbet"]}</a>')
            else:
                _cb_cell = str(v['cbet'])
            # Clickable missed count
            _ms_ids = _popup_example_ids(v.get('ids_missed', []))
            if _ms_ids:
                _ms_str = ','.join(_ms_ids)
                _ms_title = _popup_title_with_count(f"Missed c-bets on {_tex_label}",
                                                     len(v.get('ids_missed', [])))
                _ms_cell = (f'<a class="hand-list-trigger" href="#" '
                           f'data-hids="{_ms_str}" data-list-title="{_ms_title}">'
                           f'{v["opps"] - v["cbet"]}</a>')
            else:
                _ms_cell = str(v['opps'] - v['cbet'])
            doc.w(f"| {_verdict} {_tex_label} | {v['pct']:.0f}% | "
                  f"{_tgt[0]}-{_tgt[1]}% | {v['opps']} | {_cb_cell} | {_ms_cell} |")
        doc.w("")

    # GTO Texture Compliance (sample-gated)
    doc.w("**Board Texture Compliance** *(sample-gated — verdicts suppressed for thin/small)*:")
    doc.w("")
    findings = s.get('texture_gto_findings', {})
    # v7.38 (Ron's request): add 'Expected C-Bet Range' column showing what
    # hand classes SHOULD be c-betting per archetype (range composition, not
    # just frequency). Based on Dave's coaching + GTO solver baselines.
    expected_range_by_archetype = {
        'ace_high_dry':         'Range bet — every hand at small size (B20-B25)',
        'a_high_dry':           'Range bet — every hand at small size (B20-B25)',
        'dry_ahigh':            'Range bet — every hand at small size (B20-B25)',
        'ace_high_coordinated': 'Strong Ax + sets + nut FD bet B100; weaker hands check',
        'broadway_disconnected':'Bluffs + semi-bluffs + 2P+ go big (B85-B100); medium check',
        'broadway_coordinated': 'Range bet B33-B66 — no real bluffs, just value protection',
        'middling_connected':   'High-freq B50 — no range adv, equity shifts → protection',
        'middling_disconnected':'Big bet (B100-B150) with overpairs + nut FD; medium check',
        'low_connected':        '~95% check — zero range adv; bet only flush/straight draws',
        'low_ragged':           'Range bet small (B50) at 60BB+; tighten to B100 selective at <40BB',
        'paired_coordinated':   'Bet trips/2P/draws + occasional bluffs; check medium hands',
        'paired_dry':           'Range bet small — overpairs/Ax for value, hands with showdown',
        'monotone':             '~90% bet B25-B50: any FD, any made hand, any one-suit hand',
        'high_paired':          'Range bet small (B33) — value protection on K/Q/J paired',
        'low_paired':           'Range bet small (B33) — overpairs + Ax for thin value',
    }
    doc.w("| Board Texture | Side | Opps | C-Bets | C-Bet% | Target | Expected Range | Sizing OK | Sample | Verdict |")
    doc.w("|---|---|---|---|---|---|---|---|---|---|")
    _MIN_TEXTURE_N = 8
    _thin_rows = 0
    _prev_arch = None  # for group/merge
    for arch, sides in sorted(findings.items()):
        for side, d in sides.items():
            n_opps = d.get('n_opps', 0)
            if n_opps < _MIN_TEXTURE_N:
                _thin_rows += 1
                continue
            n_cbet = d.get('n_cbet', 0)
            cbet_pct = d.get('cbet_pct', 0)
            target = d.get('target_freq_pct')
            target_str = f"{target[0]}-{target[1]}%" if target else "—"
            sample_label = d.get('sample_size_label', '—')
            sizing_n = d.get('sizing_judged_n', 0)
            sizing_ok = d.get('sizing_compliant_n', 0)
            sizing_str = f"{sizing_ok}/{sizing_n}" if sizing_n else "—"
            raw_verdict = d.get('verdict', '—')
            expected_range = expected_range_by_archetype.get(arch, '—')
            if side == 'oop' and expected_range != '—':
                expected_range = expected_range + ' *(IP)*'
            if sample_label in ('thin', 'small'):
                verdict = f"⚪ {sample_label} (n={n_opps})"
            elif raw_verdict == 'compliant':
                verdict = "🟢 on target"
            elif raw_verdict == 'deviation':
                # B216 (Ron review 2026-05-25): "deviation (n=X<Y,thin)" tells
                # the player nothing actionable. State the actual problem:
                # under/over c-betting (a frequency miss), or the sizing if it
                # is a sizing miss. Direction comes from cbet% vs target band.
                _emoji = '🔴' if n_opps >= 15 else '🟡'
                _thin = '' if n_opps >= 15 else f' (n={n_opps}, thin)'
                _freq_dir = ''
                if target:
                    if cbet_pct < target[0]:
                        _freq_dir = 'under c-betting'
                    elif cbet_pct > target[1]:
                        _freq_dir = 'over c-betting'
                # Sizing miss: more than half the judged sizes were off-target.
                _sizing_off = (sizing_n and sizing_ok / sizing_n < 0.5)
                if _freq_dir:
                    verdict = f"{_emoji} {_freq_dir}{_thin}"
                elif _sizing_off:
                    verdict = (f"{_emoji} sizing off — "
                               f"{sizing_ok}/{sizing_n} on target{_thin}")
                else:
                    verdict = f"{_emoji} deviation{_thin}"
            else:
                verdict = f"⚪ {raw_verdict}"
            # Group/merge: show board texture name only on first row of each archetype
            _show_arch = (arch != _prev_arch)
            _prev_arch = arch
            # FEAT-3: make archetype name clickable on deviation rows
            _arch_cell = arch if _show_arch else ''
            if _show_arch and ('deviation' in raw_verdict or raw_verdict == 'deviation'):
                # Pick relevant hands based on deviation direction
                _tex_hids = []
                if target and cbet_pct < target[0]:
                    # Under c-betting → show hands where hero DIDN'T c-bet
                    _tex_hids = d.get('missed_hand_ids', [])
                elif target and cbet_pct > target[1]:
                    # Over c-betting → show hands where hero DID c-bet
                    _tex_hids = d.get('cbet_hand_ids', [])
                else:
                    # Generic deviation — show all hands
                    _tex_hids = (d.get('missed_hand_ids', [])
                                 + d.get('cbet_hand_ids', []))
                if _tex_hids:
                    _tex_hid_str = ','.join(_tex_hids[:30])  # cap at 30
                    _dir_lbl = ('missed c-bets' if target and cbet_pct < target[0]
                                else 'c-bets' if target and cbet_pct > target[1]
                                else 'hands')
                    _arch_cell = (
                        f'<a class="hand-list-trigger" href="#" '
                        f'data-hids="{_tex_hid_str}" '
                        f'data-list-title="{arch} {side} — {_dir_lbl}">'
                        f'{arch}</a>')
            doc.w(f"| {_arch_cell} | {side} | {n_opps} | {n_cbet} | "
                  f"{cbet_pct:.1f}% | {target_str} | {expected_range} | {sizing_str} | "
                  f"{sample_label} | {verdict} |")
    doc.w("")
    if _thin_rows:
        doc.w(f"*{_thin_rows} archetype×side combination(s) had a thin sample "
              f"(n<{_MIN_TEXTURE_N}) and are omitted — too few opportunities to "
              f"carry a c-bet-frequency signal.*")
        doc.w("")
    doc.w("*Expected Range column shows the hand-class composition that should "
          "c-bet per archetype (Dave + GTO solver baselines). The right read is "
          "'are MY c-bets coming from the right buckets,' not just 'is the % "
          "in target band'.*")
    doc.w("")

    # Board texture aggregate
    bt = s.get('board_texture', {})
    if bt:
        # Phase 4.8: renamed "Archetype" → "Board texture", column reorder
        doc.w("**Cbet by Board Texture:**")
        doc.w("")
        archetype_targets = {
            'monotone':            (35, 55),
            'two_high':            (45, 65),
            'connected_mid':       (40, 55),
            'low_dry':             (60, 80),
            'low_paired':          (55, 75),
            'high_paired':         (60, 80),
            'a_high_dry':          (65, 85),
            'low_straight':        (35, 55),
            'dry_ahigh':           (65, 85),
            'broadway_coordinated':(40, 60),
            'other':               (50, 70),
        }
        doc.w("| Board texture | Status | C-Bet% | Target | CBets/Opps |")
        doc.w("|---|:---:|---|---|---|")
        for k, v in sorted(bt.items()):
            if isinstance(v, dict):
                opps = v.get('cb_opp', 0)
                n = v.get('cb', 0)
                pct = v.get('cb_pct', 0)
                tgt = archetype_targets.get(k, (50, 70))
                verdict = _verdict_ci(n, opps, tgt[0], tgt[1], n_min=5)
                # Make out-of-target texture names clickable → hand-list popup
                _bt_cell = k
                _is_deviation = (opps >= 5 and (pct < tgt[0] or pct > tgt[1]))
                if _is_deviation:
                    _bt_hids = v.get('missed_cbet_hands', []) or []
                    if pct > tgt[1]:
                        _bt_hids = v.get('cbet_hands', []) or []
                    _bt_id_list = [h.get('id', '') if isinstance(h, dict) else str(h)
                                  for h in _bt_hids[:20]]
                    _bt_id_list = [x for x in _bt_id_list if x]
                    if _bt_id_list:
                        _bt_str = ','.join(_bt_id_list)
                        _dir = 'missed c-bets' if pct < tgt[0] else 'c-bets'
                        _bt_cell = (f'<a class="hand-list-trigger" href="#" '
                                   f'data-hids="{_bt_str}" '
                                   f'data-list-title="{k} — {_dir} ({len(_bt_id_list)})">'
                                   f'{k}</a>')
                doc.w(f"| {_bt_cell} | {verdict} | {pct:.1f}% | "
                      f"~{tgt[0]}-{tgt[1]}% | {n}/{opps} |")
        doc.w("")
        doc.w("*Targets (~) are rough population baselines — tighten as cross-session "
              "data accumulates. Sample-gated to n_min=5 (low because per-archetype "
              "samples are inherently small).*")
        doc.w("")
        # low_dry missed c-bets inline table removed — now accessible via
        # the clickable board-texture name in the table above (hand-list popup).

    # V.2 As Aggressor OOP
    doc.subsection("sec-9-2", "S9.2 As Aggressor OOP",
                   "K2 Gentlemen vs Warriors / K4 HU SRP CBet by Pos × Depth")
    k2 = s.get('k2_oop_pfr_matchup', {})
    if k2:
        # Phase 4.8: cbet%/target before hands/cbets per review
        doc.w("**K2 OOP PFR vs Caller Type** *(Warrior = LP loose caller, BvB = blind battle):*")
        doc.w("")
        doc.w("| Matchup | C-Bet% | Target | Hands | C-Bets |")
        doc.w("|---|---|---|---|---|")
        targets = {'Warrior': '35-50%', 'BvB': '40-55%', 'Gentleman': '55-70%'}
        for k, v in k2.items():
            if isinstance(v, dict):
                doc.w(f"| {k} | {v.get('pct',0):.1f}% | {targets.get(k,'—')} | "
                      f"{v.get('total',0)} | {v.get('bet',0)} |")
        doc.w("")
    k4 = s.get('k4_srp_cbet_by_pos_depth', {})
    if k4:
        # Phase 4.8: matrix layout — Position rows × Depth columns
        doc.w("**K4 HU SRP C-Bet by Position × Depth:**")
        doc.w("")
        # Detect depth buckets and positions from keys (e.g. "CO_25-40BB")
        _k4_positions = []
        _k4_depths = []
        _k4_grid = {}
        for k, v in k4.items():
            if isinstance(v, dict):
                parts = k.rsplit('_', 1)
                if len(parts) == 2:
                    pos, depth = parts
                else:
                    pos, depth = k, '—'
                if pos not in _k4_positions:
                    _k4_positions.append(pos)
                if depth not in _k4_depths:
                    _k4_depths.append(depth)
                hands_n = v.get('total', v.get('hands', 0))
                bets = v.get('bet', v.get('cbets', 0))
                pct = v.get('pct', (100*bets/hands_n if hands_n else 0))
                _k4_grid[(pos, depth)] = (pct, bets, hands_n)
        _k4_depths_sorted = sorted(_k4_depths)
        _k4_depth_hdr = " | ".join(_k4_depths_sorted)
        doc.w(f"| Position | {_k4_depth_hdr} | Total |")
        doc.w("|---" + "|---" * len(_k4_depths_sorted) + "|---|")
        for pos in _k4_positions:
            cells = []
            total_bets = total_hands = 0
            for d in _k4_depths_sorted:
                entry = _k4_grid.get((pos, d))
                if entry:
                    pct, bets, hands_n = entry
                    cells.append(f'<span data-tip="{bets}/{hands_n}">{pct:.0f}%</span>')
                    total_bets += bets
                    total_hands += hands_n
                else:
                    cells.append('—')
            total_pct = (100*total_bets/total_hands) if total_hands else 0
            total_cell = f'<span data-tip="{total_bets}/{total_hands}">{total_pct:.0f}%</span>' if total_hands else '—'
            doc.w(f"| {pos} | " + " | ".join(cells) + f" | {total_cell} |")
        # Total row
        total_cells = []
        grand_bets = grand_hands = 0
        for d in _k4_depths_sorted:
            d_bets = sum(g[1] for (p, dd), g in _k4_grid.items() if dd == d)
            d_hands = sum(g[2] for (p, dd), g in _k4_grid.items() if dd == d)
            grand_bets += d_bets
            grand_hands += d_hands
            if d_hands:
                total_cells.append(f'<span data-tip="{d_bets}/{d_hands}">{100*d_bets/d_hands:.0f}%</span>')
            else:
                total_cells.append('—')
        grand_cell = f'<span data-tip="{grand_bets}/{grand_hands}">{100*grand_bets/grand_hands:.0f}%</span>' if grand_hands else '—'
        doc.w(f"| **Total** | " + " | ".join(f"**{c}**" for c in total_cells) + f" | **{grand_cell}** |")
        doc.w("")

    # V.3 As Caller IP (Caller IP Flop Aggression M/M+/M+b)
    doc.subsection("sec-9-3", "S9.3 As Caller IP",
                   "Caller IP Flop Aggression — overall + IP Stab + IP Caller Raise")
    core = s.get('core', {})
    cipa = core.get('caller_ip_flop_agg', 0)
    cipa_n = core.get('caller_ip_flop_n')  # may be None
    cipa_mw = core.get('caller_ip_flop_agg_mw', 0)
    cipa_mw_n = core.get('caller_ip_flop_n_mw')
    _t6_rows = []
    if cipa_n:
        _t6_rows.append({"name": "Caller IP Aggression (HU)", "pct_mode": True,
                         "pct": cipa, "n": cipa_n, "target_lo": 30,
                         "target_hi": 40,
                         "notes": "raise + bet vs villain check or post-cbet"})
    else:
        # Decision #28: denom-missing fallback — show available %, ⚪ status,
        # no delta/sample (unreliable without denominator). See B13.
        _t6_rows.append(
            f"| Caller IP Aggression (HU) | ⚪ | {cipa:.1f}% | 30-40% "
            f"| — | n=— | denom missing in schema — see B13 |")
    if cipa_mw_n:
        _t6_rows.append({"name": "Caller IP Aggression (MW)", "pct_mode": True,
                         "pct": cipa_mw, "n": cipa_mw_n, "target_lo": 20,
                         "target_hi": 30, "notes": "multiway version"})
    else:
        _t6_rows.append(
            f"| Caller IP Aggression (MW) | ⚪ | {cipa_mw:.1f}% | 20-30% "
            f"| — | n=— | denom missing in schema — see B13 |")
    doc.write_block(metric_table_block("t6-caller-ip", _t6_rows))
    doc.w("")
    # IP Stab K3
    stab = s.get('ip_stab_by_board', {})
    if stab:
        # Phase 4.8: column reorder — Status, Board, Rate, Target, Bets/Total
        doc.w("**IP Stab Rate (K3 — when OOP PFR checks flop):**")
        doc.w("")
        doc.w("| Status | Board | Rate | Target | Bets/Total |")
        doc.w("|:---:|---|---|---|---|")
        for k, v in stab.items():
            if isinstance(v, dict) and v.get('total', 0) > 0:
                total_n = v.get('total', 0)
                bet_n = v.get('bet', 0)
                pct = v.get('pct', 0)
                verdict = _verdict_ci(bet_n, total_n, 60, 80, n_min=5)
                # Clickable stab/missed counts
                _stab_bids = v.get('bet_ids', [])
                _stab_mids = v.get('miss_ids', [])
                if _stab_bids or _stab_mids:
                    _all_stab = _stab_bids + _stab_mids
                    _stab_sel = _popup_example_ids(_all_stab)
                    _stab_str = ','.join(_stab_sel)
                    _stab_cell = (f'<a class="hand-list-trigger" href="#" '
                                 f'data-hids="{_stab_str}" '
                                 f'data-list-title="IP stab {k} ({bet_n} bet / {total_n - bet_n} missed)">'
                                 f'{bet_n}/{total_n}</a>')
                else:
                    _stab_cell = f'{bet_n}/{total_n}'
                doc.w(f"| {verdict} | {k} | {pct:.1f}% | "
                      f"~70%+ (Boivin K3) | {_stab_cell} |")
        doc.w("")

    # V.4 As Caller OOP (BB Defense + K6)
    doc.subsection("sec-9-4", "S9.4 As Caller OOP",
                   "BB defense + K6 Lead Profile")
    lead = s.get('flop_lead_by_board', {})
    if lead:
        # Phase 4.8: renamed "Board Archetype" → "Board texture", column reorder
        doc.w("**K6 Flop Lead Profile (BB/SB caller leading flop):**")
        doc.w("")
        doc.w("| Status | Board texture | Rate | Target | Leads/Total |")
        doc.w("|:---:|---|---|---|---|")
        for k, v in lead.items():
            if isinstance(v, dict) and v.get('total', 0) > 0:
                total_n = v.get('total', 0)
                leads_n = v.get('lead', 0)
                pct = v.get('pct', 0)
                tgt_lo, tgt_hi = 0, 15
                verdict = _verdict_ci(leads_n, total_n, tgt_lo, tgt_hi, n_min=10)
                # Clickable lead count
                _lead_ids = v.get('lead_ids', [])
                if _lead_ids:
                    _ld_sel = _popup_example_ids(_lead_ids)
                    _ld_str = ','.join(_ld_sel)
                    _ld_cell = (f'<a class="hand-list-trigger" href="#" '
                               f'data-hids="{_ld_str}" '
                               f'data-list-title="K6 leads on {k} ({leads_n})">'
                               f'{leads_n}/{total_n}</a>')
                else:
                    _ld_cell = f'{leads_n}/{total_n}'
                doc.w(f"| {verdict} | {k} | {pct:.1f}% | "
                      f"0-15% (rare line) | {_ld_cell} |")
        doc.w("")

    # V.5 Donk Profile
    doc.subsection("sec-9-5", "S9.5 Donk Profile",
                   "facing donks + Hero donk frequency")
    facing = s.get('facing_action', {})
    donk = facing.get('vs_donk', {})
    if donk and donk.get('opps', 0) > 0:
        doc.w(f"**Facing donks:** {donk.get('opps',0)} opps — "
              f"fold {donk.get('fold',0)} ({donk.get('fold_pct',0):.1f}%) | "
              f"call {donk.get('call',0)} ({donk.get('call_pct',0):.1f}%) | "
              f"raise {donk.get('raise',0)} ({donk.get('raise_pct',0):.1f}%)")
        doc.w("")
    donk_lead = facing.get('donk_lead', {})
    if donk_lead:
        flop_opps = donk_lead.get('flop_opps', 0)
        flop_n = donk_lead.get('flop_donks', 0)
        flop_pct = donk_lead.get('flop_pct', 0)
        turn_opps = donk_lead.get('turn_opps', 0)
        turn_n = donk_lead.get('turn_donks', 0)
        turn_pct = donk_lead.get('turn_pct', 0)
        doc.w("**Hero donk-leads:**")
        doc.w("")
        # B74 (v7.50, Ron 2026-05-12): add Status column. Donk-leading is a
        # rare line (<10%); above that flags 🟡/🔴.
        # Phase 4.8: column reorder — Status, Street, Rate, Target, Donks, Opps
        doc.w("| Status | Street | Rate | Target | Donks | Opps |")
        doc.w("|:---:|---|---|---|---|---|")
        for street, opps, n, pct in [('flop', flop_opps, flop_n, flop_pct),
                                       ('turn', turn_opps, turn_n, turn_pct)]:
            # BUG-Q: donk-leading is an optional exploit, not a frequency target.
            # Don't alarm red — use informational flag if elevated.
            if opps < 10:
                verdict = '⚪'
            elif pct <= 10:
                verdict = '🟢'
            elif pct <= 25:
                verdict = '📊 elevated — confirm read-based'
            else:
                verdict = '🟡 high — review if deliberate'
            # Clickable donk count
            _dk_key = f'{street}_donk_ids'
            _dk_ids = donk_lead.get(_dk_key, [])
            if _dk_ids and n > 0:
                _dk_sel = _popup_example_ids(_dk_ids, priority=1)  # P1: donk-lead deviation
                _dk_str = ','.join(_dk_sel)
                _dk_cell = (f'<a class="hand-list-trigger" href="#" '
                           f'data-hids="{_dk_str}" '
                           f'data-list-title="Hero donk-leads {street} ({n})">'
                           f'{n}</a>')
            else:
                _dk_cell = str(n)
            doc.w(f"| {verdict} | {street} | {pct:.1f}% | "
                  f"<10% (optional line) | {_dk_cell} | {opps} |")
        doc.w("")


# ============================================================
# SECTION VI — POST-FLOP 3BP & 4BP
# ============================================================

def _emit_section_vi(doc, s, rd, hands):
    """v7.39: 8-column emit with raw counts + Wilson CI + sample-size gates.
    3BP rows gate at n<20 (still typically thin in MTTs), 4BP rows gate at n<10.
    Includes B31 footnote (cbet_4bp_opps over-counts when Hero is cold-caller, not last raiser).

    v7.42 fix: cbet_by_pot_type lives at s['facing_action_v728']['cbet_by_pot_type'],
    not s['facing_action']['cbet_by_pot_type']. Prior code read the wrong path
    and got empty dicts → all-zeros rendering. The all-zeros investigator
    (gem_quality.preflight_check_all_zeros_sections) caught this for B33.
    """
    doc.section("sec-10", "S10. Post-Flop 3BP & 4BP", "raised-pot postflop play")
    fa728 = s.get('facing_action_v728', {})
    fa = s.get('facing_action', {})
    cbpt = fa728.get('cbet_by_pot_type', {}) or fa.get('cbet_by_pot_type', {})
    b3 = cbpt.get('3BP', {})
    b4 = cbpt.get('4BP', {})

    # Pull raw counts. With the v7.42 fix above, b3/b4 should be populated;
    # core fallback covers any future schema drift.
    core = s.get('core', {})
    cb3_n   = b3.get('cbets', core.get('cbet_3bp_n', 0)) or 0
    cb3_opp = b3.get('opps',  core.get('cbet_3bp_opps', 0)) or 0
    cb4_n   = b4.get('cbets', core.get('cbet_4bp_n', 0)) or 0
    cb4_opp = b4.get('opps',  core.get('cbet_4bp_opps', 0)) or 0
    f3_n    = b3.get('face_fold', core.get('fold_to_cbet_3bp_n', 0)) or 0
    f3_opp  = b3.get('face_opps', core.get('fold_to_cbet_3bp_opps', 0)) or 0
    f4_n    = b4.get('face_fold', core.get('fold_to_cbet_4bp_n', 0)) or 0
    f4_opp  = b4.get('face_opps', core.get('fold_to_cbet_4bp_opps', 0)) or 0

    doc.w("| Stat | Hero Acted | Opps | Rate | CI 90% | Target | Status | Notes |")
    doc.w("|---|---|---|---|---|---|---|---|")

    def _row(label, x, n, tlo, thi, note, n_min):
        """Per-row emitter with explicit opps + Wilson CI + n_min gate."""
        if n == 0:
            return (f"| {label} | 0 | 0 | — | — | {tlo}-{thi}% | ⚪ no opps | {note} |")
        rate = 100.0 * x / n
        ci_lo, ci_hi = _wilson_ci(x, n)
        if n < n_min:
            verdict = f"⚪ small (n={n})"
        else:
            verdict = _verdict_ci(x, n, tlo, thi, n_min=n_min)
        return (f"| {label} | {x} | {n} | {rate:.1f}% | "
                f"{ci_lo:.0f}-{ci_hi:.0f}% | {tlo}-{thi}% | {verdict} | {note} |")

    # 3BP rows: n_min=20 (3BP samples are structurally thin in MTTs;
    # below 20 a single cold streak swings rate by 5-10pp).
    doc.w(_row('C-Bet 3BP', cb3_n, cb3_opp, 50, 70,
               'as PFR (last raiser preflop)', n_min=20))
    # 4BP rows: n_min=10 (cap on how many 4BPs Hero is in per session is ~10-15;
    # below 10 the verdict is dominated by 1-2 spots — see B31 below).
    doc.w(_row('C-Bet 4BP', cb4_n, cb4_opp, 60, 80,
               'as PFR — see ⚠️ note below', n_min=10))
    doc.w(_row('Fold to 3BP CBet', f3_n, f3_opp, 40, 55,
               'as caller in 3BP', n_min=20))
    doc.w(_row('Fold to 4BP CBet', f4_n, f4_opp, 35, 50,
               'as caller in 4BP', n_min=10))
    doc.w("")

    # B247 (Ron review 2026-05-26): example links — where Hero c-bet and
    # where Hero checked back, up to 3 each, so a flagged rate is auditable
    # without guessing which hands are behind it.
    _hbid = s.get('_hands_by_id', {}) or {}

    def _ex_links(ids, cap=3):
        out = []
        for hid in (ids or [])[:cap]:
            h = _hbid.get(hid)
            out.append(_hand_ref(h) if h else f"`{str(hid)[-8:]}`")
        return ' '.join(out) if out else '—'

    for _lbl, _pt in (('3BP', b3), ('4BP', b4)):
        _cb = _pt.get('cbet_hands') or []
        _ncb = _pt.get('nocbet_hands') or []
        if _cb or _ncb:
            doc.w(f"- **C-Bet {_lbl} examples** — c-bet: {_ex_links(_cb)} · "
                  f"checked back: {_ex_links(_ncb)}")
    if (b3.get('cbet_hands') or b3.get('nocbet_hands')
            or b4.get('cbet_hands') or b4.get('nocbet_hands')):
        doc.w("")

    # ⚠️ B31 footnote — sample-quality caveat specific to this section.
    # The B31 entry in gem_known_bugs.json carries the technical detail; this
    # footnote is the user-facing crib so Ron doesn't have to cross-reference.
    if cb4_opp > 0:
        doc.w(f"⚠️ **Bug B31 — `cbet_4bp_opps` over-counts (n={cb4_opp}).** "
              f"The denominator counts hands where Hero raised pre AND it's a 4BP, "
              f"but doesn't verify Hero is the LAST raiser preflop. Hands where Hero "
              f"3-bet then *called* a 4-bet (or called a multi-jam) get counted, even "
              f"though Hero is the cold-caller, not the cbettor. Inspect the per-hand "
              f"detail before drilling. Fix planned: require pf_sequence's last raise "
              f"to be Hero. Same drift exists in `cbet_3bp_opps` at smaller magnitude.")
        doc.w("")
    doc.w("*Targets are rough population baselines. 3BP/4BP samples are structurally "
          "thin in MTTs — most flagged rates need 3-5 sessions to confirm. Per v7.39, "
          "rows render ⚪ until n≥20 (3BP) or n≥10 (4BP).*")
    doc.w("")


# ============================================================
# SECTION VII — MACRO POST-FLOP MECHANICS
# ============================================================

def _emit_section_vii(doc, s, rd, hands):
    # Ron 2026-05-11: VII section header + skim-line so reader knows where
    # to focus. Status pulls from VII.3 geometric% (the single most-actionable
    # macro metric) since sizing consistency is the recurring theme Ron is
    # working on.
    sc = s.get('sizing_consistency', {})
    geo = sc.get('geometric_pct', 0)
    geo_n = sc.get('total', 0)
    j44 = s.get('ip_3bet_sizing', {})
    dev_pct = j44.get('deviation_rate_pct', 0) or 0
    summary_bits = []
    if geo_n >= 10:
        if geo >= 75: summary_bits.append(f"sizing consistency 🟢 {geo:.0f}%")
        elif geo >= 60: summary_bits.append(f"sizing consistency 🟡 {geo:.0f}% (target ≥70%)")
        else: summary_bits.append(f"sizing consistency 🔴 {geo:.0f}% (target ≥70%)")
    if j44.get('total_count'):
        if dev_pct <= 15: summary_bits.append(f"3-bet sizing 🟢 {dev_pct:.0f}% deviations")
        elif dev_pct <= 30: summary_bits.append(f"3-bet sizing 🟡 {dev_pct:.0f}% deviations")
        else: summary_bits.append(f"3-bet sizing 🔴 {dev_pct:.0f}% deviations")
    header_summary = ' · '.join(summary_bits) if summary_bits else \
        "facing bets, sizing, bluff profile, river audit, x/r, donks"
    doc.section("sec-11", "S11. Macro Post-Flop Mechanics", header_summary)

    # VII.1 Hero Facing Bets — by sizing bucket × street
    fb = s.get('facing_bets', {})
    # B231 (Ron review 2026-05-25): when >50% of the scored buckets show the
    # same direction, the section title should SAY it ("over-folding") rather
    # than the neutral "call/fold distribution". Pre-scan to find the
    # dominant pattern.
    _targets_scan = {
        'flop_small': (70, 85), 'flop_medium': (55, 70), 'flop_large': (40, 55),
        'turn_small': (65, 80), 'turn_medium': (50, 65), 'turn_large': (35, 50),
        'river_small': (55, 75), 'river_medium': (45, 65), 'river_large': (30, 50),
    }
    _n_overfold = _n_overdefend = _n_scored = 0
    if fb:
        for _k, (_lo, _hi) in _targets_scan.items():
            _d = fb.get(_k, {})
            _tot = _d.get('call', 0) + _d.get('fold', 0)
            if _tot < 5:
                continue
            _n_scored += 1
            _dp = 100.0 * _d.get('call', 0) / _tot
            if _dp < _lo:
                _n_overfold += 1
            elif _dp > _hi:
                _n_overdefend += 1
    _viii1_sub = "call/fold distribution by street × sizing bucket"
    if _n_scored and _n_overfold > _n_scored / 2:
        _viii1_sub = (f"⚠️ over-folding — {_n_overfold} of {_n_scored} scored "
                      f"buckets defend below target")
    elif _n_scored and _n_overdefend > _n_scored / 2:
        _viii1_sub = (f"⚠️ over-defending — {_n_overdefend} of {_n_scored} "
                      f"scored buckets defend above target")
    doc.subsection("sec-11-1", "S11.1 Hero Facing Bets", _viii1_sub)
    _back_to_kpis(doc)
    # Collect fold hand IDs by street×bucket for drill-down popups
    _fold_ids_by_bucket = {}
    _call_ids_by_bucket = {}
    for h in hands:
        for _fb_st in ('flop', 'turn', 'river'):
            # Check if Hero folded to a bet on this street
            _folded = h.get(f'fold_to_villain_bet_{_fb_st}') or (
                _fb_st == 'flop' and h.get('faced_villain_cbet_flop') and not h.get('called_villain_cbet_flop')
                and not h.get('raised_villain_cbet_flop') and not h.get('xr_villain_cbet_flop'))
            _called = h.get(f'called_villain_bet_{_fb_st}') or (
                _fb_st == 'flop' and h.get('called_villain_cbet_flop'))
            if not _folded and not _called:
                continue
            # Estimate sizing bucket from action ledger
            _sz_bucket = 'medium'  # default
            for _a in (h.get('action_ledger') or []):
                if (_a.get('street') == _fb_st and _a.get('action') in ('bets', 'raises')
                        and _a.get('player') != h.get('hero')):
                    _amt = _a.get('amount_bb', 0)
                    # Rough bucket: <40% pot = small, 40-80% = medium, >80% = large
                    # We don't have pot here, so use absolute sizing as proxy
                    if _amt <= 2:
                        _sz_bucket = 'small'
                    elif _amt >= 8:
                        _sz_bucket = 'large'
                    break
            _key = f'{_fb_st}_{_sz_bucket}'
            hid = h.get('id', '')
            if _folded and hid:
                _fold_ids_by_bucket.setdefault(_key, []).append(hid)
            elif _called and hid:
                _call_ids_by_bucket.setdefault(_key, []).append(hid)
    if fb:
        # B56 (v7.47): Status column. B194 (Ron 2026-05-25): the table now
        # speaks in ONE direction — Defend% — so Ron never mentally computes
        # 1-x. Folds count is kept (raw transparency); the % column and the
        # target are both defend-side.
        # Phase 4.8: column reorder — Street, Bucket, Defend%, Target, Count, Status
        doc.w("| Street | Bucket | Defend% | Defend% Target | Count | Status |")
        doc.w("|---|---|---|---|---|---|")
        targets = {
            'flop_small':   ("70-85% (block bet → defend wider)", 70, 85),
            'flop_medium':  ("55-70%", 55, 70),
            'flop_large':   ("40-55%", 40, 55),
            'turn_small':   ("65-80%", 65, 80),
            'turn_medium':  ("50-65%", 50, 65),
            'turn_large':   ("35-50% (Jasper says 'fold more')", 35, 50),
            'river_small':  ("55-75%", 55, 75),
            'river_medium': ("45-65%", 45, 65),
            'river_large':  ("30-50% (polarized)", 30, 50),
        }
        _prev_st = None
        for st in ['flop', 'turn', 'river']:
            for bucket in ['small', 'medium', 'large']:
                key = f"{st}_{bucket}"
                d = fb.get(key, {})
                if d:
                    calls = d.get('call', 0)
                    folds = d.get('fold', 0)
                    total = calls + folds
                    fold_pct = (100.0 * folds / total) if total else 0
                    defend_pct = 100.0 - fold_pct
                    tgt_txt, lo, hi = targets.get(key, ("—", None, None))
                    if lo is None or total < 5:
                        status = f"⚪ (n={total})" if total < 5 else "⚪"
                    elif lo <= defend_pct <= hi:
                        status = "🟢"
                    elif defend_pct < lo:
                        gap = lo - defend_pct
                        status = f"🟡 over-folding ({gap:.0f}pp below)"
                    else:
                        gap = defend_pct - hi
                        status = f"🟡 over-defending ({gap:.0f}pp above)"
                    # Group first column — show street only on first row of each street
                    _st_cell = f"**{st.title()}**" if st != _prev_st else ""
                    _prev_st = st
                    # Wire fold hand IDs into count cell for drill-down
                    _fb_fids = _fold_ids_by_bucket.get(key, [])
                    if _fb_fids and folds > 0:
                        _fb_sel = _popup_example_ids(_fb_fids, priority=1)  # P1: fold-by-bucket defense
                        _fb_str = ','.join(_fb_sel)
                        _fb_title = _popup_title_with_count(
                            f"Hero folds to {st} {bucket} bet ({folds})", len(_fb_fids))
                        _fold_cell = (f'<a class="hand-list-trigger" href="#" '
                                     f'data-hids="{_fb_str}" '
                                     f'data-list-title="{_fb_title}">'
                                     f'{calls}/{total}</a>')
                    else:
                        _fold_cell = f'{calls}/{total}'
                    doc.w(f"| {_st_cell} | {bucket} | {defend_pct:.1f}% | "
                          f"{tgt_txt} | {_fold_cell} | {status} |")
        doc.w("")
        doc.w("*Targets reference Jasper-5 exploits + standard MTT defense "
              "frequency baselines. Defend% = calls / (calls+folds); Status "
              "compares it to the target band; ⚪ shown when n<5.*")
        doc.w("")
        # B3 (Aviel handoff 2026-05-25): drill-down — missed c-bet in a 3-bet
        # pot as the PFR (3-bettor). Hero 3-bet preflop, saw a flop, and did
        # NOT c-bet. In a 3BP the 3-bettor's range and nut advantage is large;
        # checking flop as the 3-bettor is a recurring missed-aggression spot.
        # BUG-1 (Ron review 2026-05-31): three failure modes fixed:
        #   (a) Exclude 4-bet+ pots — hero_3bet is True for 4-bet hands too
        #       (Hero faced a raise and re-raised), but those are 4BP not 3BP.
        #       Gate on pf_raise_count==2 (exactly 3-bet pot).
        #   (b) Exclude ALL preflop all-in scenarios — pf_allin only checks
        #       if Hero went all-in; pf_settled catches multiway all-ins too.
        #   (c) cbet_flop_3bp is gated on is_pfr — if Hero 3-bet but the
        #       c-bet classifier doesn't fire (e.g. Hero bet but action code
        #       wasn't 'cbet'), the hand falsely appears as missed. Cross-check
        #       hero_street_actions.flop for any betting action.
        _missed_3bp = [
            h for h in (hands or [])
            if isinstance(h, dict)
            and h.get('hero_3bet')
            and not h.get('hero_4bet_only') and not h.get('hero_5bet_plus')
            and (h.get('pf_raise_count') or 0) == 2  # exactly a 3-bet pot
            and len(h.get('board', []) or []) >= 3
            and not h.get('pf_allin') and not h.get('pf_settled')
            and not h.get('cbet_flop_3bp')
            # Cross-check: Hero did NOT bet flop at all (hero_street_actions)
            and (h.get('hero_street_actions', {}) or {}).get('flop', '') not in
                ('cbet', 'bet', 'raise', 'xr')
        ]
        if _missed_3bp:
            doc.w(f"**Missed c-bet in 3BP as PFR ({len(_missed_3bp)})** — Hero "
                  f"3-bet preflop, saw a flop, did not c-bet. In a 3-bet pot "
                  f"the 3-bettor owns a large range/nut advantage; a flop "
                  f"check here is a recurring missed-aggression spot"
                  + (f" (showing first 20)" if len(_missed_3bp) > 20 else "")
                  + ":")
            doc.w("")
            _x4_hdr = "| Hand Reference | Cards | Flop | Stack |"
            _x4_sep = "|---|---|---|---|"
            _x4_rows = []
            for mh in _missed_3bp[:20]:
                _ref = _hand_ref(mh)
                _flop = ' '.join((mh.get('board', []) or [])[:3]) or '—'
                # B254: _cards_text_to_pills already wraps in nowrap span —
                # don't double-wrap (causes escaped </span> in HTML output)
                _flop_nw = (_cards_text_to_pills(_flop)
                            if _flop != '—' else '—')
                _cards = ''.join(mh.get('cards', []) or [])
                _x4_rows.append(f"| {_ref} | {_cards_str_to_pills(_cards)} | "
                      f"{_flop_nw} | {round(mh.get('stack_bb',0) or 0)}BB |")
            _x4_blk = hand_evidence_table_block("vii4-missed-3bp-barrels", _x4_hdr, _x4_sep, _x4_rows)
            doc.write_block(_x4_blk)
            doc.w("")

    # VII.2 Sizing Profile — per-line
    doc.subsection("sec-11-2", "S11.2 Sizing Profile",
                   "average sizing by line type (% of pot)")
    sz = s.get('sizing', {})
    if sz:
        # Column order: Type → Street → Position (Ron review 2026-06-01)
        doc.w("| Type | Street | Position | Status | Mean | Target | Min | Max | n |")
        doc.w("|---|---|---|:---:|---|---|---|---|---|")
        size_targets = {
            'flop_cbet_IP':    ('33-66%', 33, 66),
            'flop_cbet_OOP':   ('33-50%', 33, 50),
            'turn_barrel_IP':  ('50-75%', 50, 75),
            'turn_probe_OOP':  ('33-66%', 33, 66),
            'turn_raise_OOP':  ('~3.5x', None, None),
            'river_barrel_IP': ('60-100%', 60, 100),
            'river_value_OOP': ('50-100%', 50, 100),
        }
        # Parse line key into street / type / position
        def _parse_line_key(k):
            parts = k.split('_')
            street = parts[0].title() if parts else '—'
            pos = parts[-1] if parts and parts[-1] in ('IP', 'OOP') else '—'
            action_parts = parts[1:-1] if pos != '—' else parts[1:]
            action = ' '.join(p.title() for p in action_parts) if action_parts else '—'
            return action, pos, street

        # Build rows, then sort by Type → Street for grouped display
        _sz_rows = []
        for k, v in sz.items():
            if isinstance(v, dict):
                tgt_str, lo, hi = size_targets.get(k, ('—', None, None))
                mean = v.get('avg', 0)
                n = v.get('n', 0)
                if lo is None or hi is None:
                    status = '⚪'
                elif n < 5:
                    status = f'⚪ (n={n}, thin)'
                elif lo <= mean <= hi:
                    status = '🟢'
                elif mean < lo:
                    status = f'🟡 small ({lo-mean:.0f}pp below)'
                else:
                    status = f'🟡 large ({mean-hi:.0f}pp above)'
                action, pos, street = _parse_line_key(k)
                _sz_rows.append((action, street, pos, status, mean, tgt_str, v, n))
        # Sort by Type then Street for clean grouping
        _st_order = {'Flop': 0, 'Turn': 1, 'River': 2}
        _sz_rows.sort(key=lambda r: (r[0], _st_order.get(r[1], 9)))
        _prev_type = None
        _prev_street = None
        for action, street, pos, status, mean, tgt_str, v, n in _sz_rows:
            _type_cell = f"**{action}**" if action != _prev_type else ""
            _street_cell = street if (action != _prev_type or street != _prev_street) else ""
            _prev_type = action
            _prev_street = street
            # Batch 6 (5C): cap extreme sizing values for readability
            _min_v = v.get('min', 0)
            _max_v = v.get('max', 0)
            _min_str = f"{_min_v:.0f}%" if _min_v < 1000 else f">{_min_v/100:.0f}x"
            _max_str = f"{_max_v:.0f}%" if _max_v < 1000 else f">{_max_v/100:.0f}x"
            _mean_str = f"{mean:.0f}%" if mean < 1000 else f">{mean/100:.0f}x"
            doc.w(f"| {_type_cell} | {_street_cell} | {pos} | {status} | "
                  f"{_mean_str} | {tgt_str} | "
                  f"{_min_str} | {_max_str} | {n} |")
        doc.w("")

    # VII.3 Sizing Consistency
    doc.subsection("sec-11-3", "S11.3 Sizing Consistency",
                   "manual revisit of erratic flags")
    sc = s.get('sizing_consistency', {})
    if sc:
        geo = sc.get('geometric_pct', 0)
        geo_n = sc.get('total', 0)
        verdict = _verdict_pct(geo, 70, 100, n=geo_n, n_min=10)
        doc.w(f"- **Geometric%:** {geo:.1f}% ({sc.get('geometric',0)}/{geo_n}) "
              f"| target ≥70% | {verdict}")
        doc.w(f"- **Small→small→jam count:** {sc.get('small_small_jam_count',0)} "
              f"(typically a draw-overbet-jam tell)")
        doc.w(f"- **Erratic flags:** {sc.get('erratic',0)}")
        # E5 (Ron 2026-05-11): expand erratic-sizing rows with explanation of
        # what's wrong and what would be correct. Previous table just showed
        # the streets without explaining why erratic.
        erratic_hands = sc.get('erratic_hands', [])
        if erratic_hands:
            doc.w("")
            doc.w("**Erratic-sizing hands** *(what's wrong + what would be correct):*")
            doc.w("")
            doc.w("| Hand | Cards | Streets (sizings) | What's erratic | Net BB |")
            doc.w("|---|---|---|---|---|")
            for eh in erratic_hands:
                streets = eh.get('streets', [])
                streets_str = " → ".join(f"{st} {pct:.0f}%" for st, pct in streets)
                # Heuristic explanation of WHY erratic
                if len(streets) >= 2:
                    sizes = [pct for st, pct in streets]
                    explain = []
                    if max(sizes) - min(sizes) > 100:
                        explain.append(f"size jump {min(sizes):.0f}% → {max(sizes):.0f}%")
                    if any(s > 150 for s in sizes) and any(s < 50 for s in sizes):
                        explain.append("small + overbet mix in same line")
                    if not explain:
                        explain = ["non-geometric (should be ~33-50-66% or similar progression)"]
                    explain_str = '; '.join(explain)
                else:
                    explain_str = '—'
                doc.w(f"| {_href(eh, s['_hands_by_id'])} | {_cards_str_to_pills(eh.get('cards','—'))} | "
                      f"{streets_str} | {explain_str} | "
                      f"{eh.get('net_bb',0):+.1f} |")
            doc.w("")
            doc.w("*Geometric sizing target: each street's bet should follow a "
                  "consistent fraction-of-pot progression (e.g. 1/3 → 1/2 → 2/3 "
                  "OR 1/2 → 3/4 → pot). Sudden jumps from small → overbet are "
                  "the main erratic pattern Ron is auditing for.*")
            doc.w("")

    # VII.4b Win Rate by Stack Depth (v7.64) — decision quality segmented by
    # effective stack so blind escalation and early-hand volume can't poison
    # the rate. ICM-pressure split + tournament cluster-bootstrap CI.
    _ds = rd.get('depth_segments', {}) or {}
    if _ds.get('available') and _ds.get('n_hands'):
        doc.subsection("sec-11-4b", "S11.4b Win Rate by Stack Depth",
                       "BB/100 segmented by effective stack — decision quality "
                       "isolated from blind escalation; ICM split + bootstrap CI")
        doc.w(f"*Segmenting by depth makes BB/100 commensurable again: within a "
              f"bucket the stack-in-BB is held roughly constant, so BB is the "
              f"right unit for edge and the escalating-blind problem dissolves. "
              f"{_ds['n_hands']} hands over {_ds['n_tournaments']} tournaments. "
              f"CI is a 90% tournament cluster-bootstrap (hands within a "
              f"tournament are one connected trajectory, so the tournament — "
              f"not the hand — is the independent unit). This is a "
              f"decision-quality metric; the cEV ledger in Section I remains "
              f"the separate result-attribution view. BB/100 here is realized "
              f"— the all-in-adjusted refinement is sequenced.*")
        doc.w("")
        doc.w("| Depth | Hands | % Vol | BB/100 | Std-ICM (n) | "
              "High-ICM (n) | 90% CI | Signal |")
        doc.w("|---|---|---|---|---|---|---|---|")

        def _bbf(v):
            return f"{v:+.1f}" if v is not None else "—"

        for b in _ds['buckets']:
            ci = b.get('ci90')
            ci_s = f"[{ci[0]:+.1f}, {ci[1]:+.1f}]" if ci else "—"
            sig = ("🟢 clear" if b.get('reliable_signal')
                   else ("⚪ CI straddles 0" if ci else "⚪ low n"))
            doc.w(f"| {b['depth']} | {b['n_hands']} | {b['pct_volume']:.1f}% | "
                  f"{_bbf(b['bb100'])} | {_bbf(b['bb100_std_icm'])} "
                  f"({b['n_std']}) | {_bbf(b['bb100_high_icm'])} "
                  f"({b['n_high']}) | {ci_s} | {sig} |")
        doc.w("")
        doc.w("*Std-ICM / High-ICM columns show BB/100 (hand count); High-ICM = "
              "money bubble + final table. A bucket is only a reliable signal "
              "when its 90% CI sits clear of 0 — short-stack and high-ICM cells "
              "are small-sample and will need volume before the point estimate "
              "means anything. Read the point estimates as hypotheses, the CIs "
              "as whether the data can yet support them.*")
        doc.w("")
    else:
        doc.subsection("sec-11-4b", "S11.4b Win Rate by Stack Depth",
                       "BB/100 segmented by effective stack — decision quality "
                       "isolated from blind escalation; ICM split + bootstrap CI")
        doc.w("*Depth segmentation requires multi-tournament data — insufficient "
              "sample in this session.*")
        doc.w("")

    # VII.6 River Frequency Audit
    # B9 fix (v7.46): scope clarified — RIVER ONLY (not all streets).
    doc.subsection("sec-11-6", "S11.6 River Frequency Audit — River Only",
                   "value-bet vs check-back vs bluff distribution on river decisions only")
    rb = s.get('river_audit', {})
    # Batch 3 (#6): collect river hand IDs by action category for popups
    _river_ids = {'value_bet': [], 'bluff': [], 'call': [], 'fold_to_bet': [],
                  'check_sdv': [], 'check_giveup': []}
    for h in hands:
        ra = h.get('river_action', '')
        hid = h.get('id', '')
        if ra and hid and ra in _river_ids:
            _river_ids[ra].append(hid)
    if rb:
        actions = [
            ('Value Bet',             'value_bet',     (15, 30), 'of all river decisions'),
            ('Bluff Bet',             'bluff',         (5, 15),  'of all river decisions'),
            ('Call (vs villain bet)', 'call',          (10, 25), 'of all river decisions'),
            ('Fold (vs villain bet)', 'fold_to_bet',   (15, 30), 'of all river decisions'),
            ('Check (showdown value)','check_sdv',     (15, 30), 'of all river decisions'),
            ('Check (give-up)',       'check_giveup',  (10, 20), 'of all river decisions'),
        ]
        rb_total = sum(rb.get(k, 0) for _, k, _, _ in actions)
        if rb_total:
            # Phase 4.8: column reorder — Status, Action, %, Target, Count
            doc.w("| Status | Action | % | Target | Count |")
            doc.w("|:---:|---|---|---|---|")
            for label, k, tgt, _note in actions:
                v = rb.get(k, 0)
                pct = 100*v/rb_total
                verdict = _verdict_ci(v, rb_total, tgt[0], tgt[1], n_min=15)
                _rids = _river_ids.get(k, [])
                if _rids and v > 0:
                    _sel = _popup_example_ids(_rids)
                    _rstr = ','.join(_sel)
                    _rtitle = _popup_title_with_count(f"River {label} ({v})", len(_rids))
                    _cnt_cell = (f'<a class="hand-list-trigger" href="#" '
                                f'data-hids="{_rstr}" '
                                f'data-list-title="{_rtitle}">{v}</a>')
                else:
                    _cnt_cell = str(v)
                doc.w(f"| {verdict} | {label} | {pct:.1f}% | {tgt[0]}-{tgt[1]}% | {_cnt_cell} |")
            doc.w("")
        bet_total = rb.get('value_bet', 0) + rb.get('bluff', 0)
        if bet_total:
            bluff_pct = 100.0 * rb.get('bluff', 0) / bet_total
            ci_lo, ci_hi = _wilson_ci(rb.get('bluff', 0), bet_total)
            verdict = _verdict_ci(rb.get('bluff', 0), bet_total, 25, 40, n_min=5)
            doc.w(f"**River Bluff Ratio:** {bluff_pct:.1f}% of river bets "
                  f"({rb.get('bluff',0)}/{bet_total}, CI {ci_lo:.0f}-{ci_hi:.0f}%) | "
                  f"target 25-40% | {verdict}")
            doc.w("")

    # VII.8 Bet-Fold / Bet-Call — FIXED field names (opps/fold/call/fold_pct/call_pct)
    doc.subsection("sec-11-8", "S11.8 Bet-Fold / Bet-Call",
                   "after Hero bets, faces a raise — fold or call?")
    fa = s.get('facing_action', {})
    # Batch 3 (#6): collect bet-fold/call IDs by street
    _bf_ids = {'flop': {'fold': [], 'call': []}, 'turn': {'fold': [], 'call': []},
               'river': {'fold': [], 'call': []}}
    for h in hands:
        for st_key in ('flop', 'turn', 'river'):
            if h.get(f'folded_to_xr_after_cbet') and st_key == 'flop':
                _bf_ids['flop']['fold'].append(h.get('id', ''))
            elif h.get(f'called_xr_after_cbet') and st_key == 'flop':
                _bf_ids['flop']['call'].append(h.get('id', ''))
    doc.w("| Street | Opps | Bet-Fold | Bet-Call | Fold% | Target |")
    doc.w("|---|---|---|---|---|---|")
    bf_target = (45, 60)
    for st in ['flop', 'turn', 'river']:
        bf = fa.get(f'bet_fold_{st}', {})
        opps = bf.get('opps', 0)
        if opps > 0:
            folds = bf.get('fold', 0)
            calls = bf.get('call', 0)
            fold_pct = bf.get('fold_pct', 0)
            doc.w(f"| {st} | {opps} | {folds} ({fold_pct:.1f}%) | "
                  f"{calls} ({bf.get('call_pct',0):.1f}%) | "
                  f"{fold_pct:.1f}% | {bf_target[0]}-{bf_target[1]}% |")
    doc.w("")
    doc.w("*Folding too often after betting (>65%) signals over-bluffing the bet line; "
          "calling too often (<35% fold) signals merging too many bluff-catchers into "
          "the value-bet line. Verdicts not auto-applied — context-dependent.*")
    doc.w("")

    # Phase 4.8: S11.9 Steal Defense moved to end of preflop (S8) per review.
    # Emitted from _emit_steal_defense() called in _emit_section_iv().

    # ====================================================================
    # VII.11 Aggression Gate Analysis (B58 v7.47, restructured v7.48)
    # ====================================================================
    # 5-gate detector replacing v7.46's hand-strength-only "missed value"
    # heuristic. Each candidate is evaluated against board texture, action
    # context, ER/ED axis, and "vs what calls" — false positives are
    # demoted to CORRECTLY_PASSIVE with reasoning.
    #
    # B63 (v7.48): restructured to 3×3 summary table (street × verdict)
    # with anchor links to per-cell example subsections. Each example uses
    # _hand_ref so it links to the appendix entry for full HH detail.
    agg = rd.get('aggression_analysis', {}) or {}
    has_any = (agg.get('missed_aggression') or agg.get('ambiguous')
               or agg.get('correctly_passive') or agg.get('too_aggressive')
               or agg.get('ambiguous_aggressive')
               or agg.get('correctly_aggressive'))
    if agg and 'error' not in agg and has_any:
        doc.subsection("sec-11-11", "S11.11 Bet / Check Decision Review — Missed & Over-Aggression",
                       "is each bet / check the right call?")
        doc.w("*Every passive line (a check) and aggressive line (a bet/raise) "
              "is checked against 5 plain questions: is the hand strong "
              "enough? does the board favour betting? will villain's range "
              "pay? is this a value/mixed spot rather than a pure exploit? "
              "would a worse hand call? **MISSED** = Hero checked but all five "
              "said bet — genuine missed value. **TOO AGGRESSIVE** = Hero "
              "bet/raised but most said don't — should have checked or sized "
              "down. **CORRECTLY PASSIVE / AGGRESSIVE** = the line taken was "
              "right. Each hand below says, in plain terms, what to do.*")
        doc.w("")
        # B161 (Ron 2026-05-24): bucket all SIX detector verdicts (the two
        # aggressive-side buckets — ambiguous_aggressive, correctly_aggressive
        # — were previously dropped). Six detector buckets collapse to five
        # display verdicts; both ambiguous variants share one column to match
        # Ron's label vocabulary.
        from collections import defaultdict
        buckets = defaultdict(list)
        _bucket_to_verdict = [
            ('missed_aggression',    'MISSED'),
            ('ambiguous',            'AMBIGUOUS'),
            ('ambiguous_aggressive', 'AMBIGUOUS'),
            ('correctly_passive',    'CORRECTLY_PASSIVE'),
            ('correctly_aggressive', 'CORRECTLY_AGGRESSIVE'),
            ('too_aggressive',       'TOO_AGGRESSIVE'),
        ]
        for bkey, verdict in _bucket_to_verdict:
            for c in agg.get(bkey, []) or []:
                buckets[(c.get('street_of_interest', '?'), verdict)].append(c)
        for k in buckets:
            buckets[k].sort(key=lambda c: -abs(c.get('net_bb', 0)))

        _VERDICT_ORDER = [
            ('MISSED',               '🙈'),
            ('AMBIGUOUS',            '🤷\u200d♂️'),
            ('CORRECTLY_PASSIVE',    '🛡️'),
            ('CORRECTLY_AGGRESSIVE', '🎯'),
            ('TOO_AGGRESSIVE',       '🌋'),
        ]

        doc.w("**Summary — % of evaluated candidates by street × verdict "
              "(cells link to examples):**")
        doc.w("")
        doc.w("| Street | " + " | ".join(
            f"{e} {v.replace('_',' ').title()}" for v, e in _VERDICT_ORDER)
            + " | Total |")
        doc.w("|" + "---|" * (len(_VERDICT_ORDER) + 2))
        col_totals = {v: 0 for v, _ in _VERDICT_ORDER}
        for st in ('flop', 'turn', 'river'):
            counts = {v: len(buckets[(st, v)]) for v, _ in _VERDICT_ORDER}
            row_total = sum(counts.values())
            cells = []
            for v, _e in _VERDICT_ORDER:
                n = counts[v]
                col_totals[v] += n
                if row_total == 0 or n == 0:
                    cells.append('—')
                else:
                    pct = 100.0 * n / row_total
                    # B-V10: hand-list popup instead of section anchor
                    _hids = [c.get('hand_id', '') for c in buckets[(st, v)]
                             if c.get('hand_id')][:20]
                    if _hids:
                        _hstr = ','.join(_hids)
                        _title = f"{st.title()} {v.replace('_',' ').title()} ({n})"
                        cells.append(
                            f'<a class="hand-list-trigger" href="#" '
                            f'data-hids="{_hstr}" '
                            f'data-list-title="{_title}">'
                            f'{pct:.0f}% ({n})</a>')
                    else:
                        cells.append(f"{pct:.0f}% ({n})")
            doc.w(f"| **{st}** | " + " | ".join(cells) + f" | **{row_total}** |")
        grand = sum(col_totals.values())
        if grand:
            tcells = " | ".join(
                f"**{100.0*col_totals[v]/grand:.0f}% ({col_totals[v]})**"
                for v, _ in _VERDICT_ORDER)
            doc.w(f"| **Total** | {tcells} | **{grand}** |")
        else:
            doc.w("| **Total** | "
                  + " | ".join("**0**" for _ in _VERDICT_ORDER) + " | **0** |")
        doc.w("")
        doc.w("*🙈 MISSED = Hero checked but should have bet (clear missed "
              "value). 🤷\u200d♂️ AMBIGUOUS = either line defensible. "
              "🛡️ CORRECTLY PASSIVE / 🎯 CORRECTLY AGGRESSIVE = the line "
              "taken was right. 🌋 TOO AGGRESSIVE = Hero bet/raised but "
              "shouldn't have. Each example names the exact street + action "
              "and what to do instead.*")
        doc.w("")

        # BUG-8 (Ron review 2026-05-31): each (street × verdict) cell must
        # open as an ISOLATED popup with exactly that intersection's hands.
        # The prior <details> approach had no heading boundary between blocks,
        # so the popup collector grabbed ALL adjacent <details> blocks.
        # Fix: emit each intersection as a hand_evidence_table_block with a
        # unique anchor. The existing popup mechanism recognizes these tables
        # and opens them in isolation.
        hands_by_id_local = {h.get('id'): h for h in (hands or [])
                             if isinstance(h, dict)}
        for st in ('flop', 'turn', 'river'):
            for verdict_key, verdict_emoji in _VERDICT_ORDER:
                cell = buckets[(st, verdict_key)]
                anchor = f"sec-11-11-{st}-{verdict_key.lower()}"
                if not cell:
                    # A3 fix: always emit the anchor so the summary link
                    # resolves even if this intersection has no hands.
                    doc.w(f"<<ANCHOR:{anchor}>>")
                    continue
                vbase = verdict_key.replace('_', ' ').title()
                vlabel = f"{verdict_emoji} {st.upper()} — {vbase}"
                # Build table rows for this intersection
                _xi_hdr = ("| Hand Reference | Cards | Board | Hand Class "
                           "| Net | What to do |")
                _xi_sep = "|---|---|---|---|---|---|"
                _xi_rows = []
                for c in cell[:10]:
                    h = hands_by_id_local.get(c.get('hand_id'))
                    ref = _hand_ref(h) if h else f"`{(c.get('hand_id') or '')[-8:]}`"
                    cards = _cards_str_to_pills(
                        (c.get('cards', '') or '').replace(' ', ''))
                    hand_class = c.get('hand_class', '')
                    board = _cards_text_to_pills(c.get('board', '') or '—')
                    net = c.get('net_bb', 0)
                    commentary = _agg_commentary(c)
                    _xi_rows.append(
                        f"| {ref} | {cards} | {board} | "
                        f"{hand_class} | {net:+.1f}BB | {commentary} |")
                # Wrap in <details> so the table is collapsed by default.
                # The summary cell links #sec-11-11-{st}-{verdict} and the
                # auto-open JS opens the targeted <details> on hash change.
                doc.w(f"<a id=\"{anchor}\"></a>")
                doc.w(f"<details><summary><strong>{vlabel} ({len(cell)} hand"
                      f"{'s' if len(cell) != 1 else ''}"
                      f") — click to expand</strong></summary>")
                doc.w("")
                doc.w(_xi_hdr)
                doc.w(_xi_sep)
                for _r in _xi_rows:
                    doc.w(_r)
                doc.w("")
                doc.w("</details>")
                doc.w("")

    _emit_sub_opponent_archetype(doc, s, rd, hands)


# ============================================================
# SECTIONS VIII-XIII
# ============================================================

def _emit_section_viii(doc, s, rd, hands):
    doc.section("sec-5", "S5. Action Card & GTO Shortlist",
                "drills + GTO Wizard import list (clustered by leak pattern)")

    # VIII.1 Promoted Leaks
    doc.subsection("sec-5-1", "S5.1 Promoted Leaks",
                   "the leaks to actually work on next session")
    promoted = (rd.get('leak_persistence', {}) or {}).get('current_leaks', [])
    # B219 (Ron review 2026-05-25): "what is this / how does it help?" — the
    # section was a bare numbered list with no framing. Explain it.
    doc.w("*This is the session's shortlist of leaks worth deliberate "
          "practice — the metric-flagged patterns from the Strategic Leaks section "
          "that persisted or recurred, promoted here so next session has a "
          "concrete focus list instead of \"play better\". Each links into "
          "Strategic Leaks for the analyst judgment (real leak vs. noise) and the "
          "example hands; IV.2 Top Drills turns them into exercises.*")
    doc.w("")
    if promoted:
        for i, leak in enumerate(promoted, 1):
            name = leak.get('name', leak.get('leak', '—')) if isinstance(leak, dict) else str(leak)
            doc.w(f"{i}. {name} — {_xref('sec-3', label='see S3')}")
    else:
        doc.w("⚪ No promoted leaks this session — nothing recurred or "
              "persisted at a level worth a dedicated drill.")
    doc.w("")

    # VIII.2 Top Drills
    doc.subsection("sec-5-2", "S5.2 Top Drills",
                   "specific exercises mapped to leaks/observations")
    drills = _generate_cheat_sheet(s, rd, hands)
    for d in drills:
        doc.w(f"- {d}")
    doc.w("")

    # VIII.3 GTO Wizard Shortlist (clustered)
    doc.subsection("sec-5-3", "S5.3 GTO Wizard Shortlist",
                   "clustered by leak pattern — drag-and-drop into GTOW")
    shortlist = rd.get('gto_shortlist', [])
    if shortlist:
        # Try to cluster by leak pattern if available
        clusters = defaultdict(list)
        for h in shortlist:
            cluster = h.get('cluster', h.get('pattern', 'general'))
            clusters[cluster].append(h)
        for cluster_name, items in clusters.items():
            doc.w(f"**Cluster: {cluster_name}**")
            doc.w("")
            doc.w("| # | Hand | Cards | Spot | Question for solver |")
            doc.w("|---|---|---|---|---|")
            for i, h in enumerate(items, 1):
                # E7 (Ron 2026-05-11): build more specific drill questions
                # — previous "line check" was too vague. Build from
                # position/depth/pot-type/board if available.
                question = (h.get('question', '') or '').replace('fold_preflop', 'preflop fold').replace('check_fold', 'check-fold')
                if not question or question.strip().lower() in ('line check', 'review'):
                    pos = h.get('position', '?')
                    stack = h.get('stack_bb', 0)
                    pot = h.get('pot_type', 'SRP')
                    board = h.get('board', [])
                    if isinstance(board, list):
                        board_str = ' '.join(board[:3]) if board else '—'
                    else:
                        board_str = board
                    question = (f"{pos} {stack:.0f}BB {pot}: "
                                f"verify GTO frequency/sizing on flop {board_str}")
                # B185 (Ron review 2026-05-25): enrich Spot with draw type +
                # SPR (spec: show draw type / SPR / stacks / position).
                _full = s.get('_hands_by_id', {}).get(h.get('id'), {})
                _spr = _full.get('spr', h.get('spr'))
                _draw = _full.get('draw_type', h.get('draw_type'))
                _spot_bits = [f"{h.get('position','?')} {h.get('stack_bb',0):.0f}BB",
                              h.get('pot_type', 'SRP')]
                if _draw and str(_draw) not in ('none', 'made_hand', '—', 'None'):
                    _spot_bits.append(str(_draw))
                if isinstance(_spr, (int, float)) and _spr > 0:
                    _spot_bits.append(f"SPR {_spr:.1f}")
                spot = ' · '.join(_spot_bits)
                # B192 (Ron 2026-05-25): Cards column was raw text ("Qd Ac") —
                # render as colored card pills like every other section.
                doc.w(f"| {i} | {_hand_ref(h)} | "
                      f"{_cards_str_to_pills((h.get('cards','—') or '').replace(' ',''))} | "
                      f"{spot} | {_cards_text_to_pills(question)} |")
            doc.w("")
        doc.w(f"*Export file (GG-format): `{rd.get('gto_export_path','—')}`*")
        doc.w("")
    else:
        doc.w("⚪ No hands flagged for GTO review this session.")
        doc.w("")



def _emit_section_ix(doc, s, rd, hands):
    persistence = rd.get('leak_persistence', {})
    # FIXED v7.36: data shape is {'summary': {...counts}, 'tracker': [...entries], ...}.
    # Earlier renderer read persistence.get('new', []) at top level which doesn't
    # exist — always emitted "0 new | 0 recurring | 0 resolved" + empty table.
    summary = persistence.get('summary', {})
    tracker = persistence.get('tracker', [])
    n_new = summary.get('new', 0)
    n_recurring = summary.get('recurring', 0)
    n_resolved = summary.get('resolved', 0)
    doc.section("sec-12", "S12. Leak Persistence Tracker",
                f"{n_new} new | {n_recurring} recurring | {n_resolved} resolved")

    # Severity legend
    doc.w("*Severity: 🔴 HIGH = recurring 3+ sessions OR rate >2x target deviation. "
          "🟡 MED = recurring 2 sessions OR 1-2x deviation. ⚪ LOW = new or minor.*")
    doc.w("")
    if tracker:
        # B18 (v7.46): expanded columns — added n (sample size) and
        # EV cost (BB/100) so Ron can prioritize which leaks to attack first.
        doc.w("| Leak | Status | Severity | Current | Target | n | EV cost (BB/100) | Gap |")
        doc.w("|---|---|---|---|---|---|---|---|")
        # Sort by EV cost descending — biggest financial impact first
        sortable_tracker = sorted(
            [e for e in tracker if isinstance(e, dict)],
            key=lambda e: -float(e.get('ev_cost_per100_bb', 0) or 0))
        for entry in sortable_tracker:
            name = entry.get('leak', entry.get('name', '—'))
            status = entry.get('status', '—')
            severity = entry.get('severity', '⚪ LOW' if '🆕' in status else '🟡 MED')
            current_raw = entry.get('current', '—')
            if isinstance(current_raw, (int, float)):
                current = f"{current_raw:.1f}%"
            else:
                current = str(current_raw)
            target = entry.get('target', '—')
            gap = entry.get('gap', '—')
            n_obs = entry.get('n', 0) or 0
            ev_cost = entry.get('ev_cost_per100_bb', 0) or 0
            ev_str = f"{ev_cost:.2f}" if ev_cost else '—'
            # Anchor — prefer explicit anchor field (B18 enrichment), fallback _leak_meta
            xref_target = entry.get('anchor') or entry.get('xref')
            if not xref_target:
                try:
                    _det, _anch, _lbl = _leak_meta(name)
                    xref_target = _anch
                except Exception:
                    xref_target = None
            name_with_link = f"{name} {_xref(xref_target, label='↗')}" if xref_target else name
            doc.w(f"| {name_with_link} | {status} | {severity} | "
                  f"{current} | {target} | {n_obs} | {ev_str} | {gap} |")
        doc.w("")
        doc.w("*Sorted by estimated EV cost (BB/100). EV estimates are "
              "rough — `gap_pp × scaling_factor` per metric. Use as priority "
              "ordering, not absolute dollar figures. Notes column: see ↗ "
              "for the metric's detail section.*")
        doc.w("")

    # Progress Tracker
    doc.subsection("sec-12-1", "S12.1 Progress Tracker",
                   "comparison vs previous sessions")
    trend = rd.get('trend_data', [])
    if trend:
        doc.w("| Session | Hands | bb/100 | Mistakes/100 |")
        doc.w("|---|---|---|---|")
        for t in trend[-5:]:
            # v7.42 fix: trend_data uses CSV-style capitalised keys
            # ('Date', 'Hands', 'BB_per_100', 'Mistakes_per_100'), not the
            # lowercase _ snakecase the renderer was reading. Coerce numerics
            # since CSV values arrive as strings.
            date = t.get('Date') or t.get('date') or '—'
            hands_v = t.get('Hands') or t.get('hands') or 0
            bb100 = t.get('BB_per_100') or t.get('bb_per_100') or 0
            mp100 = t.get('Mistakes_per_100') or t.get('mistakes_per_100') or 0
            try:
                hands_v = int(float(hands_v) if hands_v else 0)
            except (TypeError, ValueError):
                hands_v = 0
            try:
                bb100 = float(bb100) if bb100 not in ('', None) else 0.0
            except (TypeError, ValueError):
                bb100 = 0.0
            try:
                mp100 = float(mp100) if mp100 not in ('', None) else 0.0
            except (TypeError, ValueError):
                mp100 = 0.0
            doc.w(f"| {date} | {hands_v} | "
                  f"{bb100:+.1f} | {mp100:.2f} |")
        # v8.12.4 (QA item 21): close the trend with the CURRENT session —
        # five historical rows with no "today" line left the comparison
        # without its subject.
        _csv_cur = s.get('csv_row', {}) or {}
        _cur_date = _csv_cur.get('Date') or s.get('volume', {}).get('date', 'this session')
        try:
            _cur_bb = float(_csv_cur.get('BB_per_100') or 0)
        except (TypeError, ValueError):
            _cur_bb = 0.0
        _cur_hands = s.get('volume', {}).get('hands', len(hands))
        _dt_cur = (rd.get('discipline_tier') or {})
        _cur_mp = _dt_cur.get('canonical_mistakes_per_100',
                              _dt_cur.get('mistakes_per_100', 0)) or 0
        doc.w(f"| **{_cur_date} (this session)** | **{_cur_hands}** | "
              f"**{_cur_bb:+.1f}** | **{_cur_mp:.2f}** |")
        doc.w("")
    else:
        doc.w("⚠️ NEEDS: Comparison vs previous session (no trend data available — first session in tracker?)")
        doc.w("")

    # Learnings This Run
    doc.subsection("sec-12-2", "S12.2 Learnings This Run",
                   "what the analyzer flagged as unexpected this pass")
    # Try report_data first, then fall back to quality.learnings
    learnings = rd.get('learnings_this_run', [])
    if not learnings:
        learnings = s.get('quality', {}).get('learnings', [])
    if learnings:
        doc.w("| Category | Observation | Suggested Action |")
        doc.w("|---|---|---|")
        for ln in learnings:
            doc.w(f"| {ln.get('category','—')} | {ln.get('observation','—')} | "
                  f"{ln.get('suggested_action', ln.get('action','—'))} |")
        doc.w("")
    else:
        doc.w("⚪ No new learnings this run.")
        doc.w("")


def _emit_section_x(doc, s, rd, hands):
    doc.section("sec-14", "S14. Pipeline QA",
                "technical metadata, bug tracker, analysis coverage")
    # v8.3.0: Renderer version in QA metadata
    from gem_report_draft.draft import VERSION
    doc.w(f"**Renderer:** {VERSION}")
    doc.w("")
    # P3 #17: Self-reporting QA block
    _ie_issues = rd.get('issue_explorer_issues', [])
    _ie_hands = sum(len(i.get('all_hand_ids', [])) for i in _ie_issues)
    _app_ids = rd.get('appendix_hand_ids_all', [])
    _n_analyst = len([k for k in (rd.get('analyst_commentary', {}) or {})
                      if not k.startswith('__') and isinstance((rd.get('analyst_commentary', {}) or {}).get(k), dict)
                      and (rd.get('analyst_commentary', {}) or {})[k].get('verdict')])
    doc.w("<details><summary><strong>Report Build QA</strong></summary>")
    doc.w("")
    doc.w(f"- Issue Explorer rows: {len(_ie_issues)}")
    doc.w(f"- IE representative hand references: {_ie_hands}")
    doc.w(f"- Appendix hand detail cards: {len(_app_ids)}")
    doc.w(f"- Analyst verdicts written: {_n_analyst}")
    # Pipeline timing (from run_log if available)
    _rl = rd.get('run_log', {}) or {}
    _timing = _rl.get('timing', {}) or {}
    if _timing:
        doc.w(f"- Pipeline timing: parse {_timing.get('parse_s','?')}s · "
              f"analyze {_timing.get('analyze_s','?')}s · "
              f"render {_timing.get('render_s','?')}s · "
              f"total {_timing.get('total_s','?')}s")
    doc.w(f"- Viewport meta: present")
    doc.w(f"- Hand queue JS: initialized")
    doc.w("")
    doc.w("</details>")
    doc.w("")
    # v7.36: bug list moved out of source code into gem_known_bugs.json so the
    # renderer reads a data file rather than carrying ~80 lines of hardcoded
    # tuples. Resolves the architectural issue caught in 2026-05-08 review:
    # bug status was being maintained in two places (this file + GEM_KNOWN_BUGS.md).
    # v7.37: Search order matches D35 — prefer local /home/claude/ copy when
    # present (so iterative bug-list edits are visible to the same-run renderer),
    # fall back to /mnt/project/ as the canonical clean-checkout source.
    import os, json as _json
    bug_paths = [os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'gem_known_bugs.json'),
                 'gem_known_bugs.json',
                 '/mnt/project/gem_known_bugs.json']
    bug_data = None
    for bp in bug_paths:
        if os.path.exists(bp):
            try:
                with open(bp) as f:
                    bug_data = _json.load(f)
                break
            except Exception:
                continue
    if not bug_data:
        doc.w("⚠️ `gem_known_bugs.json` not found — bug tracker unavailable this run.")
        doc.w("")
        return

    open_bugs = bug_data.get('open_bugs', [])
    retracted = bug_data.get('retracted', [])
    fixed = bug_data.get('fixed', [])

    if open_bugs:
        doc.w(f"**Open ({len(open_bugs)}):**")
        doc.w("")
        doc.w("| # | Bug | Severity | Status |")
        doc.w("|---|---|---|---|")
        for b in open_bugs:
            # Escape pipe chars in cell content with backslash so markdown
            # table parser doesn't treat them as column delimiters (HTML-
            # entity escape gets double-escaped by _html_escape).
            def _esc(s): return (s or '').replace('|', '\\|')
            doc.w(f"| {_esc(b.get('id','?'))} | {_esc(b.get('summary','—'))} | "
                  f"{_esc(b.get('severity','—'))} | {_esc(b.get('status','—'))} |")
        doc.w("")
    else:
        doc.w("👍 No open bugs.")
        doc.w("")

    if fixed:
        # B115 (Ron 2026-05-20): the "Recently fixed" changelog list was
        # redundant with the open-bugs table (the table is what's actionable)
        # and added ~15 rows of noise. Fixed-bug history stays in
        # gem_known_bugs.json for audit; the report shows a one-line pointer.
        doc.w(f"*{len(fixed)} fixed bug(s) archived in `gem_known_bugs.json` "
              "(full history retained for audit; not rendered here).*")
        doc.w("")

    if retracted:
        doc.w("**Retracted (was wrongly flagged as bug):**")
        doc.w("")
        for r in retracted:
            doc.w(f"- ~~{r.get('id','?')}: {r.get('summary','—')}~~ — {r.get('note','')}")
        doc.w("")

    doc.w("*Bug tracker is now data-driven (gem_known_bugs.json). Add/update bugs "
          "via that JSON, not by editing renderer source.*")
    doc.w("")

    # v8.2.1: Analysis Coverage QA table (moved from IE to QA, collapsed)
    _cov = rd.get('issue_explorer_coverage', [])
    if _cov:
        from gem_report_draft.sections_issue_explorer import emit_coverage_qa_table
        emit_coverage_qa_table(doc, _cov)


def _emit_section_xi(doc, s, rd, hands):
    doc.section("sec-15", "S15. Complete Stat Reference",
                "every CSV column for cross-session regression tracking")
    csv = s.get('csv_row', {})
    if csv:
        doc.w("**Group A: Volume + Results**")
        doc.w("")
        _emit_csv_group(doc, csv, ['Date','Hands','Tournaments','Bullets','Net_BB',
                                    'BB_per_100','EV_BB_per_100','Avg_Buyin'])
        # Group A.1: skill_index family (Ron 2026-05-16). Separate group so the
        # ELO-scale metrics are easy to spot in the dump.
        doc.w("**Group A.1: Skill Index Family**")
        doc.w("")
        _emit_csv_group(doc, csv, ['Skill_Index','Skill_Index_Handicap',
                                    'FinScore_Pct','AvgPos_Pct','Mean_Logit'])
        doc.w("**Group B: Pre-Flop Headlines**")
        doc.w("")
        _emit_csv_group(doc, csv, ['VPIP','PFR','ThreeBet','ThreeBet_IP','ThreeBet_OOP',
                                    'Cold_Call_NB','Hero_4Bet','Hero_5Bet'])
        doc.w("**Group C: Position Profile**")
        doc.w("")
        _emit_csv_group(doc, csv, ['Open_UTG','Open_UTG1','Open_MP','Open_HJ',
                                    'Open_CO','Open_BTN','Open_SB',
                                    'BB_Defense_vs_Steal','SB_Defense_vs_LP'])
        doc.w("**Group D: Postflop Aggression**")
        doc.w("")
        _emit_csv_group(doc, csv, ['AF','AFq','HU_IP_CBet','HU_OOP_CBet','MW_CBet',
                                    'Turn_CBet','River_CBet'])
        doc.w("**Group E: Showdown**")
        doc.w("")
        _emit_csv_group(doc, csv, ['WTSD_Vol','WSD_Vol','WWSF','Non_SD_Win','SD_Aggressor'])
        doc.w("**Group F: Bluff Profile**")
        doc.w("")
        _emit_csv_group(doc, csv, ['Pure_Bluff_Pct','Semi_Bluff_Pct','Value_Bet_Pct'])
        doc.w("**Group G: Facing Bets**")
        doc.w("")
        _emit_csv_group(doc, csv, ['Fold_to_CBet','Call_CBet','Raise_CBet',
                                    'Fold_to_3Bet_IP','Fold_to_3Bet_OOP',
                                    'Fold_to_BB_3Bet'])
        doc.w("**Group H-O (other groups):**")
        doc.w("")
        # Dump remaining as a 2-col table
        _emit_csv_remaining(doc, csv)


def _emit_csv_group(doc, csv, fields):
    # Clean None values to '—' (Python None AND string 'None' leak into rendered text)
    def _clean(v):
        if v is None or v == 'None' or v == '':
            return '—'
        return v
    rows = [(f, _clean(csv.get(f))) for f in fields if f in csv]
    if not rows:
        return
    doc.w("| Field | Value | Field | Value |")
    doc.w("|---|---|---|---|")
    for i in range(0, len(rows), 2):
        a = rows[i]
        b = rows[i+1] if i+1 < len(rows) else ('', '')
        _av = a[1] if (a[1] is not None and a[1] != 'None') else '—'
        _bv = b[1] if (b[1] is not None and b[1] != 'None') else '—'
        doc.w(f"| {a[0]} | {_av} | {b[0]} | {_bv} |")
    doc.w("")


def _emit_csv_remaining(doc, csv):
    seen = {'Date','Hands','Tournaments','Bullets','Net_BB','BB_per_100','EV_BB_per_100',
            'Avg_Buyin','VPIP','PFR','ThreeBet','ThreeBet_IP','ThreeBet_OOP','Cold_Call_NB',
            'Hero_4Bet','Hero_5Bet','Open_UTG','Open_UTG1','Open_MP','Open_HJ','Open_CO',
            'Open_BTN','Open_SB','BB_Defense_vs_Steal','SB_Defense_vs_LP','AF','AFq',
            'HU_IP_CBet','HU_OOP_CBet','MW_CBet','Turn_CBet','River_CBet','WTSD_Vol','WSD_Vol',
            'WWSF','Non_SD_Win','SD_Aggressor','Pure_Bluff_Pct','Semi_Bluff_Pct','Value_Bet_Pct',
            'Fold_to_CBet','Call_CBet','Raise_CBet','Fold_to_3Bet_IP','Fold_to_3Bet_OOP',
            'Fold_to_BB_3Bet'}
    rows = [(k, v) for k, v in csv.items()
            if k not in seen and v not in (None, '', 'None')]
    if not rows:
        return
    doc.w("| Field | Value | Field | Value |")
    doc.w("|---|---|---|---|")
    for i in range(0, len(rows), 2):
        a = rows[i]
        b = rows[i+1] if i+1 < len(rows) else ('', '')
        _av = a[1] if (a[1] is not None and a[1] != 'None') else '—'
        _bv = b[1] if (b[1] is not None and b[1] != 'None') else '—'
        doc.w(f"| {a[0]} | {_av} | {b[0]} | {_bv} |")
    doc.w("")


# ============================================================
# EXTRACTED SUBSECTION HELPERS
# Each has signature _emit_sub_XXX(doc, s, rd, hands) and emits
# exactly one doc.subsection() plus all content through to the
# next subsection / section boundary.  Placed here so any
# section emitter can call them in any order.
# ============================================================


def _emit_sub_ip_3bet_sizing(doc, s, rd, hands):
    # VII.4 IP 3-Bet Sizing by Depth (Dave J44)
    doc.subsection("sec-11-4", "S11.4 IP 3-Bet Sizing by Depth (Dave J44)",
                   "depth-stratified targets: <25BB→2.5x, 25-40BB→3.0x, >40BB→3.5x")
    j44 = s.get('ip_3bet_sizing', {})
    buckets = j44.get('buckets', {})
    if buckets:
        # E6 (Ron 2026-05-11): show deviations as % of total + average
        # deviation magnitude so Ron doesn't have to calculate
        total_3b = j44.get('total_count', 0)
        dev_n = j44.get('deviation_count', 0)
        dev_pct = (100.0 * dev_n / total_3b) if total_3b else 0
        # Average deviation magnitude across all dev rows
        all_dev_records = []
        for k, v in buckets.items():
            for d in v.get('deviations', []):
                all_dev_records.append(d)
        avg_dev_x = (sum(d.get('deviation', 0) for d in all_dev_records) / len(all_dev_records)
                     if all_dev_records else 0)
        doc.w(f"**Total IP 3-bets:** {total_3b} | "
              f"**Deviations:** {dev_n}/{total_3b} = **{dev_pct:.1f}%** "
              f"(avg size delta: {avg_dev_x:+.2f}x) | "
              f"**Flag threshold:** {j44.get('flag_threshold', '—')}")
        doc.w("")
        doc.w("| Depth | Hands | Mean Sizing | Target | Status |")
        doc.w("|---|---|---|---|---|")
        for k in ['<25BB', '25-40BB', '40+BB']:
            v = buckets.get(k, {})
            mean = v.get('mean_size_x')
            mean_str = f"{mean:.2f}x" if mean else "—"
            target = v.get('target', '—')
            target_str = f"{target}x" if target else "—"
            n = v.get('count', 0)
            devs_n = len(v.get('deviations', []))
            status = "🟢" if devs_n == 0 and n > 0 else (
                "🟡" if devs_n <= 1 else ("🔴" if devs_n >= 2 else "⚪"))
            bucket_dev_pct = (100.0 * devs_n / n) if n else 0
            doc.w(f"| {k} | {n} | {mean_str} | {target_str} | "
                  f"{status} ({devs_n}/{n} = {bucket_dev_pct:.0f}% deviation) |")
        doc.w("")
        all_devs = []
        for k, v in buckets.items():
            for d in v.get('deviations', []):
                all_devs.append((k, d))
        # B232 (Ron review 2026-05-25): the deviations table order looked
        # random — it followed dict-iteration order. Sort it logically:
        # primary = depth bucket (shallow → deep), secondary = deviation
        # magnitude (biggest |Act/Tgt−1| first within each depth). So the
        # reader scans depth-banded, worst-offender-first.
        _depth_rank = {'<25BB': 0, '25-40BB': 1, '40+BB': 2}

        def _dev_sort_key(item):
            depth, d = item
            sx = d.get('size_x', 0) or 0
            tx = d.get('target_x', 0) or 0
            mag = abs(sx / tx - 1.0) if tx else 0.0
            return (_depth_rank.get(depth, 9), -mag)

        all_devs.sort(key=_dev_sort_key)
        if all_devs:
            doc.w("**Sizing deviations:**")
            doc.w("")
            # B205 (Ron review 2026-05-25): surface the DOMINANT recurring
            # deviation as an aggregate line — Ron noticed "the vast majority
            # is 3-betting 2.5-2.75x at 40BB+ instead of 3.5x" and wants that
            # called out (and tracked as recurrent), not just listed row by
            # row. Group by depth-bucket + direction, report the biggest cell.
            from collections import Counter as _Ctr
            _pat = _Ctr()
            _pat_sizes = {}
            for _dep, _d in all_devs:
                _sx = _d.get('size_x', 0) or 0
                _tx = _d.get('target_x', 0) or 0
                if not _tx:
                    continue
                _dir = 'undersized' if _sx < _tx else 'oversized'
                _key = (_dep, _dir)
                _pat[_key] += 1
                _pat_sizes.setdefault(_key, []).append(_sx)
            if _pat:
                (_tdep, _tdir), _tn = _pat.most_common(1)[0]
                if _tn >= 3 and _tn >= 0.5 * len(all_devs):
                    _szs = _pat_sizes[(_tdep, _tdir)]
                    _lo, _hi = min(_szs), max(_szs)
                    _tgt = buckets.get(_tdep, {}).get('target', '?')
                    doc.w(f"> **Recurring pattern:** {_tn} of {len(all_devs)} "
                          f"sizing deviations are **{_tdir} 3-bets at "
                          f"{_tdep}** — averaging {sum(_szs)/len(_szs):.2f}x "
                          f"(range {_lo:.2f}–{_hi:.2f}x) against the {_tgt}x "
                          f"target. This is a single, trackable habit, not "
                          f"scattered noise — one sizing adjustment closes it.")
                    doc.w("")
            # B195 (Ron 2026-05-25): three fixes —
            #  (1) Cards rendered from the REAL hand (suits) not the normalized
            #      hand-class string ('A7s'), which made the pill renderer
            #      default every hand to spades.
            #  (2) Δ column = Actual/Target - 1, shown as a %, per Ron's spec.
            #  (3) Verdict thumb: a deviation is not automatically wrong, so
            #      the verdict is magnitude-based — small size-grid divergence
            #      is fine (👍), only a material gap is flagged (👎).
            _x5_hdr = ("| Hand Reference | Cards | Depth | Actual | Target | "
                       "Δ (Act/Tgt−1) | Verdict |")
            _x5_sep = "|---|---|---|---|---|---|---|"
            _x5_rows = []
            # B232: rows are ordered by depth bucket (shallow → deep), then by
            # deviation magnitude (worst first within each depth).
            for depth, d in all_devs:
                _full = s.get('_hands_by_id', {}).get(d.get('id'), {})
                _real = _full.get('cards')
                if isinstance(_real, list) and _real:
                    cards_cell = _cards_str_to_pills(''.join(_real))
                else:
                    cards_cell = _cards_str_to_pills(d.get('cards', '—'))
                size_x = d.get('size_x', 0) or 0
                target_x = d.get('target_x', 0) or 0
                if target_x:
                    delta_pct = (size_x / target_x - 1.0) * 100.0
                    delta_str = f"{delta_pct:+.0f}%"
                    ad = abs(delta_pct)
                    if ad <= 15:
                        verdict = "👍 on-pattern"
                    elif ad <= 35:
                        verdict = "🟡 notable"
                    else:
                        verdict = "👎 off-pattern"
                else:
                    delta_str, verdict = "—", "⚪"
                # _href → _hand_ref citation side-effect fires HERE — same point
                _x5_rows.append(f"| {_href(d, s['_hands_by_id'])} | {cards_cell} | "
                      f"{depth} | {size_x:.2f}x | {target_x:.1f}x | "
                      f"{delta_str} | {verdict} |")
            _x5_blk = hand_evidence_table_block("ix-sizing-devs",
                _x5_hdr, _x5_sep, _x5_rows)
            doc.write_block(_x5_blk)
            doc.w("")
            doc.w("*Δ = Actual ÷ Target − 1. Verdict is magnitude-based, not an "
                  "EV ruling — a 3-bet sizing within ±15% of target is normal "
                  "bet-grid variation (👍); ±15-35% is notable (🟡); beyond "
                  "±35% the sizing materially diverges from the J44 target "
                  "(👎) and is worth a deliberate look — depth / ICM / a "
                  "specific villain read can still justify it.*")
            doc.w("")


def _emit_sub_bluff_all_streets(doc, s, rd, hands):
    # VII.5 Bluff Profile (full)
    # B9 fix (v7.46): clarify scope vs VII.6 river audit. VII.5 classifies
    # bet decisions across ALL STREETS (flop+turn+river combined). VII.6
    # is river-only. Both use the word "bluff" but with different
    # denominators — flagged at section level to prevent confusion.
    doc.subsection("sec-11-5", "S11.5 Bluff Profile — All Streets (flop+turn+river)",
                   "value/semi/pure breakdown across all bet decisions — sample-gated + Wilson CI")
    doc.w("<<ANCHOR:tbl-bluff-profile>>")
    bp = s.get('bluff_profile', {})
    total = bp.get('total', 0)
    if total > 0:
        doc.w(f"*Scope: all flop/turn/river bet decisions combined ({total} total). "
              f"For river-only breakdown, see VII.6.*")
        doc.w("")
        doc.w(f"**Total bet decisions:** {total} "
              f"(value={bp.get('value',0)}, semi-bluff={bp.get('semi',0)}, "
              f"pure-bluff={bp.get('pure',0)})")
        doc.w("")
        doc.w("| Class | Count | Rate | CI 90% | Target | Status |")
        doc.w("|---|---|---|---|---|---|")
        _bp_id_map = {
            'Value Bet (all streets)': bp.get('value_ids', []),
            'Semi-Bluff (all streets)': bp.get('semi_ids', []),
            'Pure Bluff (all streets)': bp.get('pure_ids', []),
        }
        for label, x, lo, hi in [
            ('Value Bet (all streets)', bp.get('value', 0), 50, 70),
            ('Semi-Bluff (all streets)', bp.get('semi', 0), 15, 30),
            ('Pure Bluff (all streets)', bp.get('pure', 0), 10, 20),
        ]:
            rate = 100.0 * x / total if total else 0
            ci_lo, ci_hi = _wilson_ci(x, total)
            verdict = _verdict_ci(x, total, lo, hi, n_min=10)
            _bp_pool = list(set(_bp_id_map.get(label, [])))
            _bp_hids = _popup_example_ids(_bp_pool)
            if _bp_hids and x > 0:
                _bp_str = ','.join(_bp_hids)
                _bp_title = _popup_title_with_count(f"{label} ({x})", len(_bp_pool))
                _x_cell = (f'<a class="hand-list-trigger" href="#" '
                           f'data-hids="{_bp_str}" '
                           f'data-list-title="{_bp_title}">'
                           f'{x}</a>')
            else:
                _x_cell = str(x)
            doc.w(f"| {label} | {_x_cell} | {rate:.1f}% | "
                  f"{ci_lo:.0f}-{ci_hi:.0f}% | {lo}-{hi}% | {verdict} |")
        doc.w("")


def _emit_sub_cr_frequency(doc, s, rd, hands):
    # VII.7 Check-Raise Frequency — FIXED field names
    doc.subsection("sec-11-7", "S11.7 Check-Raise Frequency",
                   "by street with sample-size gate")
    _back_to_kpis(doc)
    doc.w("<<ANCHOR:tbl-check-raise-frequency>>")
    cr = s.get('cr_frequency', {})
    # F3 (v7.49, Ron 2026-05-13): identify "avoidable CRs" — hands matching the
    # L1 BB-CR-pattern signature (x/r flop → multi-street commit → significant
    # loss). When found, surface as a collapsible details block below the
    # table, and link from each street's Status cell to the relevant section.
    avoidable_by_street = {'flop': [], 'turn': [], 'river': []}
    for _h in (hands or []):
        if not isinstance(_h, dict):
            continue
        act_sum = (_h.get('action_summary') or '').lower()
        net = _h.get('net_bb') or 0
        # L1 signature: x/r on flop + at least one subsequent commit street + significant loss
        has_xr_flop = 'x/r flop' in act_sum
        commit_turn = ('bet turn' in act_sum and '75%' in act_sum) or 'jam turn' in act_sum
        commit_river = ('bet river' in act_sum and ('75%' in act_sum or '65%' in act_sum)) or 'jam river' in act_sum
        # Trigger street = whichever commit happened (river overrides turn for tagging)
        if has_xr_flop and net <= -25 and (commit_turn or commit_river):
            if commit_river:
                avoidable_by_street['river'].append(_h)
            elif commit_turn:
                avoidable_by_street['turn'].append(_h)
            else:
                avoidable_by_street['flop'].append(_h)
    n_avoidable_total = sum(len(v) for v in avoidable_by_street.values())

    # FEAT-4 (v7.99): per-hand CR IDs for clickable cells
    _cr_hids = cr.get('cr_hids', {}) or {}
    # v8.3.0: missed check-raise hand IDs (where Hero had strong hand OOP vs cbet)
    _mcr_ids = (s.get('popup_hand_ids') or {}).get('missed_cr_flop_ids', [])

    doc.w("| Street | Opps | CRs | Rate | CI 90% | Target | Missed | Status |")
    doc.w("|---|---|---|---|---|---|---|---|")
    for st, target in [('flop', (6, 8)), ('turn', (3, 5)), ('river', (2, 4))]:
        opps = cr.get(f'{st}_opp', 0)        # FIXED: singular 'opp'
        crs = cr.get(f'{st}_cr', 0)          # FIXED: 'cr' not 'count'
        pct = cr.get(f'{st}_pct', 0)
        ci_lo, ci_hi = _wilson_ci(crs, opps)
        verdict = _verdict_ci(crs, opps, target[0], target[1], n_min=10)
        # F3: append example link to Status when avoidable CRs exist on this street
        _avoid_st = avoidable_by_street.get(st, [])
        n_avoid = len(_avoid_st)
        verdict_cell = verdict
        if n_avoid > 0:
            verdict_cell = f"{verdict} · [⚠️ {n_avoid} avoidable ↓](#sec-11-7-avoidable)"
        # FEAT-4: make rate cell clickable → shows ALL CR hands for this street
        _rate_cell = f"{pct:.1f}%"
        _st_cr_hids = _cr_hids.get(st, [])
        if _st_cr_hids:
            _cr_hid_str = ','.join(_st_cr_hids[:30])
            _rate_cell = (f'<a class="hand-list-trigger" href="#" '
                         f'data-hids="{_cr_hid_str}" '
                         f'data-list-title="Check-raises — {st} ({len(_st_cr_hids)})">'
                         f'{pct:.1f}%</a>')
        # Missed CR column: clickable count of missed check-raise opportunities
        _missed_cell = '—'
        if st == 'flop' and _mcr_ids:
            _mcr_str = ','.join(_mcr_ids[:20])
            _missed_cell = (f'<a class="hand-list-trigger" href="#" '
                           f'data-hids="{_mcr_str}" '
                           f'data-list-title="Missed check-raises — flop ({len(_mcr_ids)})">'
                           f'{len(_mcr_ids)}</a>')
        doc.w(f"| {st} | {opps} | {crs} | {_rate_cell} | "
              f"{ci_lo:.0f}-{ci_hi:.0f}% | {target[0]}-{target[1]}% | {_missed_cell} | {verdict_cell} |")
    # Total
    total_opp = cr.get('total_opp', 0)
    total_cr = cr.get('total_cr', 0)
    total_pct = cr.get('total_pct', 0)
    ci_lo, ci_hi = _wilson_ci(total_cr, total_opp)
    verdict = _verdict_ci(total_cr, total_opp, 8, 12, n_min=10)
    verdict_total = verdict
    if n_avoidable_total > 0:
        verdict_total = f"{verdict} · [⚠️ {n_avoidable_total} avoidable ↓](#sec-11-7-avoidable)"
    # FEAT-4: total rate clickable → shows all CR hands across streets
    _total_rate = f"{total_pct:.1f}%"
    _all_cr_hids = []
    for _st in ('flop', 'turn', 'river'):
        _all_cr_hids.extend(_cr_hids.get(_st, []))
    if _all_cr_hids:
        _all_cr_hid_str = ','.join(_all_cr_hids[:30])
        _total_rate = (f'<a class="hand-list-trigger" href="#" '
                      f'data-hids="{_all_cr_hid_str}" '
                      f'data-list-title="All check-raises ({len(_all_cr_hids)})">'
                      f'{total_pct:.1f}%</a>')
    doc.w(f"| **Total** | {total_opp} | {total_cr} | {_total_rate} | "
          f"{ci_lo:.0f}-{ci_hi:.0f}% | 8-12% | {len(_mcr_ids) if _mcr_ids else '—'} | {verdict_total} |")
    doc.w("")

    # F3 (v7.49): collapsible "Avoidable CRs" section with L1-signature hands
    if n_avoidable_total > 0:
        doc.w(f'<a id="sec-11-7-avoidable"></a>')
        doc.w(f'<a id="sec-viii-7-avoidable" class="anchor-compat"></a>')
        doc.w("")
        doc.w(f"<details><summary><strong>⚠️ {n_avoidable_total} Avoidable CR{'s' if n_avoidable_total != 1 else ''} "
              f"— {_coach.describe('L1')} — click to expand</strong></summary>")
        doc.w("")
        doc.w(f"*These hands match leak **{_coach.describe('L1')}** "
              "(Leaks Index): "
              "Hero check-raised the flop with semi-bluff or value, villain called, then "
              "Hero overcommitted on turn/river when the board changed unfavorably or "
              "the draw busted. Fix: pre-x/r plan with explicit turn-card branches; "
              "never half-barrel when SDV=0; smaller x/r sizing (2.2-2.5x) to preserve SPR. "
              "See L1 entry for full framework.*")
        doc.w("")
        # Sort each street's hands by |net_bb| descending
        for st in ('flop', 'turn', 'river'):
            cell_hands = avoidable_by_street.get(st, [])
            if not cell_hands:
                continue
            cell_hands.sort(key=lambda h: h.get('net_bb', 0))  # most negative first
            doc.w(f"**{st.upper()} commit ({len(cell_hands)} hand{'s' if len(cell_hands) != 1 else ''}):**")
            doc.w("")
            for _h in cell_hands:
                ref = _hand_ref(_h)
                cards = _cards_str_to_pills(''.join(_h.get('cards', [])))
                board = _cards_text_to_pills(' '.join((_h.get('board') or [])[:5]))
                net = _h.get('net_bb', 0)
                act = (_h.get('action_summary') or '')[:80]
                doc.w(f"- {ref} — {cards} on {board} | net {net:+.1f}BB · _{act}_")
            doc.w("")
        doc.w("</details>")
        doc.w("")
        # F3 (v7.49): also stamp a citation back-ref so the appendix link reads
        # nicely (sec-viii-7-avoidable doesn't have a doc.subsection, so the
        # citation tracker needs to know about it explicitly).
        for st_hands in avoidable_by_street.values():
            for _h in st_hands:
                if _h.get('id'):
                    # Hand was just referenced from this subsection — register
                    # citation so appendix back-link block shows VII.7 avoidable.
                    _state._record_citation_explicit(
                        _h['id'], 'sec-11-7-avoidable', 'S11.7 Avoidable CRs (L1)')


def _emit_sub_af_breakdown(doc, s, rd, hands):
    # ====================================================================
    # VII.10 AF Breakdown by Street × Position × Role (B59 v7.47)
    # ====================================================================
    # Session-level AF aggregates over very different decision classes
    # (cbet IP vs call OOP vs river barrel). The breakdown surfaces the
    # specific slice driving the leak.
    afb = rd.get('af_breakdown', {}) or {}
    if afb and 'error' not in afb:
        doc.subsection("sec-11-10", "S11.10 AF Breakdown — by Street × Position × Role",
                       "decomposed AF; session-level number aggregates over too many decision classes")
        _back_to_kpis(doc)
        doc.w("*Session AF aggregates across very different decision types (cbet IP, call OOP, "
              "river barrel). The breakdown below shows which **specific slice** is driving the "
              "leak — and therefore which drill to prioritize.*")
        doc.w("")
        # Session row first
        ses = afb.get('session', {})
        if ses:
            doc.w(f"**Session AF:** {ses.get('status', '⚪')} **{ses.get('af_display', '—')}** · "
                  f"target {ses.get('target_band', '—')} · n={ses.get('n', 0)} · {ses.get('note', '')}")
            doc.w("")
        # By-street + by-position + by-role table
        doc.w("**By street:**")
        doc.w("")
        doc.w("| Street | Bets | Raises | Calls | AF | Target | Status |")
        doc.w("|---|---|---|---|---|---|---|")
        for st_name in ('flop', 'turn', 'river'):
            st = afb.get('by_street', {}).get(st_name, {})
            if st:
                doc.w(f"| {st_name} | {st.get('bets', 0)} | {st.get('raises', 0)} | "
                      f"{st.get('calls', 0)} | {st.get('af_display', '—')} | "
                      f"{st.get('target_band', '—')} | {st.get('status', '⚪')} {st.get('note', '')} |")
        doc.w("")
        doc.w("**By position:**")
        doc.w("")
        doc.w("| Position | Bets | Raises | Calls | AF | Target | Status |")
        doc.w("|---|---|---|---|---|---|---|")
        for pos_name in ('ip', 'oop'):
            ps = afb.get('by_position', {}).get(pos_name, {})
            if ps:
                doc.w(f"| {pos_name.upper()} | {ps.get('bets', 0)} | {ps.get('raises', 0)} | "
                      f"{ps.get('calls', 0)} | {ps.get('af_display', '—')} | "
                      f"{ps.get('target_band', '—')} | {ps.get('status', '⚪')} {ps.get('note', '')} |")
        doc.w("")
        doc.w("**By role:**")
        doc.w("")
        doc.w("| Role | Bets | Raises | Calls | AF | Target | Status |")
        doc.w("|---|---|---|---|---|---|---|")
        for role_name in ('pfr', 'caller'):
            rs = afb.get('by_role', {}).get(role_name, {})
            if rs:
                doc.w(f"| {role_name.upper()} | {rs.get('bets', 0)} | {rs.get('raises', 0)} | "
                      f"{rs.get('calls', 0)} | {rs.get('af_display', '—')} | "
                      f"{rs.get('target_band', '—')} | {rs.get('status', '⚪')} {rs.get('note', '')} |")
        doc.w("")
        # Cross-tabs — only show n>=5 cells
        # FEAT-10: split the single "Slice" column into Street, Position, Role
        doc.w("**Cross-slice (n≥5):**")
        doc.w("")
        doc.w("| Role | Street | Position | n | AF | Target | Status |")
        doc.w("|---|---|---|---|---|---|---|")
        cross = afb.get('cross', {})
        def _sort_key(item):
            key, slc = item
            af = slc.get('af')
            tb = slc.get('target_band', '0-0')
            if af is None or '—' in tb: return 999
            try:
                lo = float(tb.split('-')[0])
                return lo - af
            except Exception:
                return 999
        # B-V10: sort by role (Caller first, then PFR), then street order,
        # then position. Group rows by Role for readability.
        _STREET_ORD = {'flop': 0, 'turn': 1, 'river': 2}
        _POS_ORD = {'oop': 0, 'ip': 1}
        _ROLE_ORD = {'caller': 0, 'pfr': 1}
        cross_sorted = sorted(
            [(k, v) for k, v in cross.items() if v.get('n', 0) >= 5],
            key=lambda kv: (
                _ROLE_ORD.get(str(kv[0]).split('_')[-1], 9),
                _STREET_ORD.get(str(kv[0]).split('_')[0], 9),
                _POS_ORD.get(str(kv[0]).split('_')[1] if '_' in str(kv[0]) else '', 9),
            ))
        any_shown = False
        _prev_role = None
        for key, slc in cross_sorted:
            any_shown = True
            # Parse key "flop_oop_caller" → Street=Flop, Pos=OOP, Role=Caller
            _parts = str(key).split('_')
            _st_col = _parts[0].title() if len(_parts) >= 1 else '—'
            _pos_col = _parts[1].upper() if len(_parts) >= 2 else '—'
            _role_col = _parts[2].title() if len(_parts) >= 3 else '—'
            # Group by Role — show role label on first row only
            _role_cell = _role_col if _role_col != _prev_role else ''
            _prev_role = _role_col
            doc.w(f"| {_role_cell} | {_st_col} | {_pos_col} | "
                  f"{slc.get('n', 0)} | {slc.get('af_display', '—')} | "
                  f"{slc.get('target_band', '—')} | {slc.get('status', '⚪')} {slc.get('note', '')} |")
        if not any_shown:
            doc.w("| (no cross-slices have n≥5) | | | | | | |")
        doc.w("")
        # B62 (v7.48, Ron 2026-05-12): removed duplicate "Below-target slices
        # (action items)" block — it restated the same data already shown in
        # the by-street / by-position / by-role / cross-slice tables above.


def _emit_sub_cr_made(doc, s, rd, hands):
    # VIII.4 Check-Raises Hero Made
    # B164 (Ron 2026-05-24): section was titled "Check-Raise Candidates Hero
    # Missed" but cr_evidence_hands collects hands where Hero DID check-raise
    # (`check_raises` non-empty). Title now matches the data — these are
    # Hero's actual check-raises, surfaced for spot/sizing review.
    doc.subsection("sec-5-4", "S5.4 Check-Raises Hero Made",
                   "every flop/turn/river x/r Hero made this session — review spot selection & sizing")
    cr_evidence = rd.get('cr_evidence_hands', [])
    if cr_evidence:
        # B44 fix (v7.44): cr_evidence_hands carries street/board/hand_strength/
        # draw_type/line — NOT 'spot'/'xr_type' the old code expected. Also
        # missing stack_bb, so _hand_ref rendered 0BB; switch to _href which
        # backfills from _hands_by_id.
        # B193 (Ron 2026-05-25): add a Verdict column using the same emoji
        # taxonomy as everywhere else. Pulled from the analyst pass; a hand
        # with no verdict shows ⚪ (not reviewed — not a leak claim).
        _crv_analyst = rd.get('analyst_commentary', {}) or {}
        def _verdict_emoji(hid):
            cmt = _crv_analyst.get(hid)
            if not isinstance(cmt, dict):
                return '⚪'
            v = (cmt.get('verdict', '') or '')
            if v.startswith('I.7'):    return '❄️ cooler'
            if v.startswith('III.0'):  return '⚖️ GTO-std'
            if v.startswith('III.1'):  return '👎 punt'
            if v.startswith('III.2'):  return '👎 mistake'
            if v.startswith('III.3'):  return '👍 cleared'
            if v.startswith('III.4'):  return '📖 read-dep'
            if v.startswith('III.5'):  return '👍 justified'
            if v.startswith('III.8'):  return '⭐ pick'
            if v.startswith('no leak'): return '👍 no leak'
            return '⚪'
        _x6_hdr = ("| Hand Reference | Street | Board | Hand | Draw | Line | "
                   "Net | Verdict |")
        _x6_sep = "|---|---|---|---|---|---|---|---|"
        _x6_rows = []
        for c in cr_evidence:
            spot_summary = f"{c.get('hand_strength','—')}"
            draw = c.get('draw_type', 'none')
            if draw and draw != 'none':
                draw_cell = draw
            else:
                draw_cell = '—'
            net = c.get('net_bb', 0)
            _x6_rows.append(f"| {_href(c, s['_hands_by_id'])} | {c.get('street','—')} | "
                  f"{_cards_text_to_pills(c.get('board','—') or '—')} | "
                  f"{spot_summary} | {draw_cell} | "
                  f"`{c.get('line','—')}` | {net:+.1f} BB | "
                  f"{_verdict_emoji(c.get('id'))} |")
        # X6: 8 domain-specific columns (Street/Board/Hand/Draw/Line/Net/Verdict)
        # — structurally a raw evidence ledger, not a hand-review table.
        # raw_reference preserves real tabular structure without forcing §3
        # hand_evidence column mapping onto incompatible poker-line data.
        _x6_blk = raw_reference_block("viii-cr-evidence", _x6_hdr, _x6_sep, _x6_rows)
        doc.write_block(_x6_blk)
        doc.w("")
        doc.w("*Verdict ⚪ = check-raise not individually analyst-reviewed "
              "(most are standard); ❄️/👍/📖/👎 carry the analyst's call.*")
        doc.w("")
    else:
        doc.w("⚪ No check-raises made this session.")
        doc.w("")


def _emit_sub_agg_drills(doc, s, rd, hands):
    # VIII.5 Aggression Drill Clusters (B67 v7.48)
    # Group missed-aggression candidates by AF below-target leak class.
    # Each cluster has a focused tactical question + top-5 example hands
    # linked to the appendix. Replaces generic "review missed value spots".
    drill_clusters = rd.get('aggression_drill_clusters', []) or []
    if drill_clusters:
        doc.subsection("sec-5-5", "S5.5 Aggression Drill Clusters",
                       "missed-aggression spots grouped by AF below-target slice; one focused drill per cluster")
        doc.w("*Each cluster ties a session-level AF leak (e.g., `river_ip_pfr` "
              "AF=0.20 vs target 1.5-3.0) to the specific hands that fed it. "
              "Drill the question against the top-5 spots — they're the concrete "
              "instances of the abstract leak.*")
        doc.w("")
        hands_by_id_local = {h.get('id'): h for h in (hands or []) if isinstance(h, dict)}
        for i, cluster in enumerate(drill_clusters, 1):
            slice_key = cluster.get('slice_key', '?')
            af_disp = cluster.get('slice_af_display', '—')
            target = cluster.get('slice_target', '—')
            gap = cluster.get('slice_gap', 0)
            n_slice = cluster.get('slice_n', 0)
            n_spots = cluster.get('spot_count', 0)
            doc.w(f"**Cluster {i} — `{slice_key}` · AF {af_disp} vs target {target} "
                  f"({gap:+.2f} below) · slice n={n_slice} · {n_spots} missed-agg spot{'s' if n_spots != 1 else ''}**")
            doc.w("")
            doc.w(f"> {cluster.get('drill_question', '—')}")
            doc.w("")
            spots = cluster.get('spots', []) or []
            if spots:
                # B218 (Ron review 2026-05-25): the cluster spots were a loose
                # bullet list — render them as a table so the drill instances
                # are scannable (cards / hand class / board / axis / net /
                # solver) in aligned columns.
                doc.w("| Hand | Cards | Hand Class | Board | Axis | Net | Solver |")
                doc.w("|---|---|---|---|---|---|---|")
                for c in spots:
                    h = hands_by_id_local.get(c.get('hand_id'))
                    ref = _hand_ref(h) if h else f"`{(c.get('hand_id') or '')[-8:]}`"
                    sv = c.get('solver_verdict') or '—'
                    _board = c.get('board', '') or '—'
                    # B254: _cards_text_to_pills already wraps in nowrap span
                    _board_nw = (_cards_text_to_pills(_board)
                                 if _board != '—' else '—')
                    _cards_p = _cards_str_to_pills((c.get('cards', '') or '').replace(' ', ''))
                    doc.w(f"| {ref} | {_cards_p} | "
                          f"{c.get('hand_class', '')} | {_board_nw} | "
                          f"{c.get('decision_axis', '')} | "
                          f"{c.get('net_bb', 0):+.1f}BB | {sv} |")
                doc.w("")
    else:
        doc.subsection("sec-5-5", "S5.5 Aggression Drill Clusters",
                       "missed-aggression spots grouped by AF below-target slice; one focused drill per cluster")
        doc.w("*All AF slices are within target ranges this session — no drill "
              "clusters generated.*")
        doc.w("")


def _emit_sub_solver_confirm(doc, s, rd, hands):
    # VIII.6 Solver Confirmation Pass (B66 v7.48)
    sp = rd.get('aggression_solver_pass', {}) or {}
    if sp and 'error' not in sp:
        confirmed = sp.get('confirmed', [])
        denied = sp.get('denied', [])
        skipped = sp.get('skipped', [])
        if confirmed or denied or skipped:
            doc.subsection("sec-5-6", "S5.6 Solver Confirmation Pass",
                           "river HU missed-aggression candidates cross-checked against gem_solver value-bet EV")
            doc.w(f"**Summary:** {len(confirmed)} CONFIRMED · "
                  f"{len(denied)} DENIED · "
                  f"{len(skipped)} SKIPPED")
            doc.w("")
            # B221 (Ron review 2026-05-25): if EVERY candidate skipped with
            # `no_hero_bet`, the section produced nothing and looked buggy.
            # Root cause: this pass tests hands where Hero CHECKED the river,
            # but the solver value-bet branch reads Hero's ACTUAL river bet
            # from the reconstructed context — which is 0 when Hero checked —
            # so it returns `no_hero_bet` and skips. The synthetic-bet side
            # channel that would feed a hypothetical bet into the solver was
            # never wired up. State that honestly rather than show empty stats.
            _skip_reasons = [sk.get('reason', '') for sk in skipped]
            _all_no_bet = (skipped and not confirmed and not denied
                           and all(r == 'no_hero_bet' for r in _skip_reasons))
            if _all_no_bet:
                doc.w("> ⚠️ **Known limitation — this pass did not evaluate any "
                      "hand.** It tests river spots where Hero *checked*, but "
                      "the solver value-bet branch keys off Hero's actual "
                      "river bet (zero when Hero checked), so every candidate "
                      "skips as `no_hero_bet`. The synthetic-bet path that "
                      "would feed a hypothetical bet into the solver is not "
                      "yet wired up — until it is, IV.6 cannot confirm or deny "
                      "missed-river-bet flags. Tracked as a pipeline TODO.")
                doc.w("")
            # B224/B230 (Ron review 2026-05-25): render the CONFIRMED hands,
            # not just a count. The candidate set is the solver pass's own
            # `candidates` list — the heuristic flags PLUS the top-30
            # river-check screen (B230) — so every confirmed/denied hand
            # resolves even if it was never in missed_aggression.
            _solver_cands = sp.get('candidates', [])
            if not _solver_cands:
                _solver_cands = (rd.get('aggression_analysis', {}) or {}).get(
                    'missed_aggression', [])
            cand_by_id = {c.get('hand_id'): c for c in _solver_cands}
            hands_by_id_local = {h.get('id'): h for h in (hands or []) if isinstance(h, dict)}
            # Phase 4.8: removed "Evaluated N river-check candidates..." text per review
            if confirmed:
                doc.w("**Confirmed missed value — solver agrees Hero should "
                      "have bet (test sizing 60% pot):**")
                doc.w("")
                doc.w("| Hand | Cards | Spot | EV(bet) | EV(check) | Δ bet−check |")
                doc.w("|---|---|---|---|---|---|")
                for hid in confirmed:
                    c = cand_by_id.get(hid, {})
                    h = hands_by_id_local.get(hid)
                    ref = _hand_ref(h) if h else f"`{hid[-8:]}`"
                    _evb = c.get('solver_ev_bet')
                    _evc = c.get('solver_ev_check')
                    _evd = c.get('solver_ev_delta')
                    _spot = (f"{c.get('hand_class', '')} on "
                             f"{_cards_text_to_pills(c.get('board', '') or '—')}")
                    _cards_p = _cards_str_to_pills((c.get('cards', '') or '').replace(' ', ''))
                    _fb = f"{_evb:+.2f} BB" if isinstance(_evb, (int, float)) else "—"
                    _fc = f"{_evc:+.2f} BB" if isinstance(_evc, (int, float)) else "—"
                    _fd = f"**{_evd:+.2f} BB**" if isinstance(_evd, (int, float)) else "—"
                    doc.w(f"| {ref} | {_cards_p} | {_spot} | {_fb} | {_fc} | {_fd} |")
                    # B225: record the citation so the confirmed hand's
                    # appendix detail back-links to IV.6.
                    _state._record_citation_explicit(
                        hid, 'sec-5-6', "S5.6 Solver Confirmation Pass")
                doc.w("")
            if denied:
                # Phase 4.8: collapsed table format per review
                doc.w(f"<details><summary><strong>Heuristic flags overruled by solver "
                      f"({len(denied)})</strong> — downgraded from MISSED → AMBIGUOUS"
                      f"</summary>")
                doc.w("")
                doc.w("| Hand | Cards | Spot | Solver Verdict |")
                doc.w("|---|---|---|---|")
                for hid in denied:
                    c = cand_by_id.get(hid, {})
                    h = hands_by_id_local.get(hid)
                    ref = _hand_ref(h) if h else f"`{hid[-8:]}`"
                    sv = c.get('solver_verdict', '—')
                    _cards_p = _cards_str_to_pills((c.get('cards', '') or '').replace(' ', ''))
                    _spot = (f"{c.get('hand_class', '')} on "
                             f"{_cards_text_to_pills(c.get('board', '') or '—')}")
                    doc.w(f"| {ref} | {_cards_p} | {_spot} | {sv} |")
                doc.w("")
                doc.w("</details>")
                doc.w("")
            if skipped and len(skipped) > 0:
                # Just count types of skip reasons
                from collections import Counter
                reasons = Counter(sk.get('reason', 'unknown') for sk in skipped)
                doc.w(f"<details><summary>Skipped reasons ({len(skipped)} total)</summary>")
                doc.w("")
                for reason, cnt in reasons.most_common():
                    doc.w(f"- {reason}: {cnt}")
                doc.w("")
                doc.w("</details>")
                doc.w("")
        else:
            doc.subsection("sec-5-6", "S5.6 Solver Confirmation Pass",
                           "river HU missed-aggression candidates cross-checked against gem_solver value-bet EV")
            doc.w("*No river-check candidates met the screening threshold this session.*")
            doc.w("")
    else:
        doc.subsection("sec-5-6", "S5.6 Solver Confirmation Pass",
                       "river HU missed-aggression candidates cross-checked against gem_solver value-bet EV")
        _sp_err = sp.get('error', '') if isinstance(sp, dict) else ''
        if _sp_err:
            doc.w(f"*Solver pass encountered an error: {_sp_err}*")
        else:
            doc.w("*Solver pass data unavailable for this session.*")
        doc.w("")


def _emit_sub_bounty_pko(doc, s, rd, hands):
    # ---- IV.7 Bounty / PKO Equity Adjustments (B226/B227, Ron 2026-05-25) ----
    # Per-hand flip analysis: preflop all-in decisions whose correct/incorrect
    # verdict flips between the freezeout and bounty regimes. Scope: HU preflop
    # all-ins, bounty formats — Hero as caller (B226) and as jammer (B227).
    pko = rd.get('pko_flips', {}) or {}
    _flips_a = pko.get('flips_a', []) or []
    _flips_b = pko.get('flips_b', []) or []
    _n_flip = len(_flips_a) + len(_flips_b)
    doc.subsection("sec-5-7", "S5.7 Bounty / PKO Equity Adjustments",
                   (f"{_n_flip} bounty-flip spot(s) — decisions the bounty changes"
                    if _n_flip else
                    "no HU all-in decision changed under the current PKO "
                    "all-in model — multiway and BB-defense PKO spots are "
                    "evaluated separately (S4.2/S4.3)"))
    if 'error' in pko:
        doc.w(f"⚠️ PKO analysis unavailable: `{pko['error']}`")
        doc.w("")
    else:
        # Phase 4.8: long description → data-tip on a summary line
        _ev = pko.get('evaluated', 0)
        _evc = pko.get('evaluated_caller', 0)
        _evj = pko.get('evaluated_jammer', 0)
        _el = pko.get('eligible', 0)
        doc.w(f'<span data-tip="A flip is a preflop all-in decision whose '
              f'correct/incorrect verdict changes between the freezeout regime '
              f'and the bounty regime. The bounty only adds value when Hero '
              f'covers the opponent (winning also claims the bounty). Scope: '
              f'heads-up preflop all-ins in bounty/PKO formats — both '
              f'Hero-as-caller (jam-call pot odds) and Hero-as-jammer (shove '
              f'EV with bounty fold-equity value). Evaluated {_ev} of {_el} '
              f'bounty-format preflop all-ins ({_evc} caller, {_evj} jammer).'
              f'">Evaluated {_ev} of {_el} bounty all-ins — hover for '
              f'methodology</span>')
        doc.w("")

        def _caller_table(rows, title, note):
            # Phase 4.8: note → data-tip on title
            _note_text = note.strip().lstrip('*').rstrip('*')
            doc.w(f'<span data-tip="{_html_escape(_note_text)}">'
                  f'**{title}**</span>')
            doc.w("")
            doc.w("| Hand | Cards | Hero eq | Req eq (freezeout) | "
                  "Req eq (bounty) | Covers? |")
            doc.w("|---|---|---|---|---|---|")
            for sp in rows:
                # B-B: register citation so XIV.B emits the appendix stub
                _state._record_citation(sp['id'])
                _hr = (f"[`{sp['id'][-8:]}`](#sec-app-hand-{sp['id'][-8:]}) • "
                       f"{(sp.get('tournament') or '')[:30]} ({sp.get('date','')})")
                doc.w(f"| {_hr} | {_cards_str_to_pills(sp['cards'])} | "
                      f"{sp['hero_equity']:.1f}% | {sp['required_fo']:.1f}% | "
                      f"{sp['required_pko']:.1f}% | "
                      f"{'✅ yes' if sp['hero_covers'] else '— no'} |")
            doc.w("")

        def _jammer_table(rows, title, note):
            # Phase 4.8: note → data-tip on title
            _note_text = note.strip().lstrip('*').rstrip('*')
            doc.w(f'<span data-tip="{_html_escape(_note_text)}">'
                  f'**{title}**</span>')
            doc.w("")
            doc.w("| Hand | Cards | Hero eq | EV shove (freezeout) | "
                  "EV shove (bounty) | Covers? |")
            doc.w("|---|---|---|---|---|---|")
            for sp in rows:
                # B-B: register citation so XIV.B emits the appendix stub
                _state._record_citation(sp['id'])
                _hr = (f"[`{sp['id'][-8:]}`](#sec-app-hand-{sp['id'][-8:]}) • "
                       f"{(sp.get('tournament') or '')[:30]} ({sp.get('date','')})")
                doc.w(f"| {_hr} | {_cards_str_to_pills(sp['cards'])} | "
                      f"{sp['hero_equity']:.1f}% | "
                      f"{sp['ev_freezeout_bb']:+.2f} BB | "
                      f"{sp['ev_bounty_bb']:+.2f} BB | "
                      f"{'✅ yes' if sp['hero_covers'] else '— no'} |")
            doc.w("")

        for grp, lab_a, lab_b, note_a, note_b in [
            ('caller',
             "(a) Call correct WITH the bounty — a fold without",
             "(b) Call correct WITHOUT the bounty — a fold with it",
             "*The bounty discount is what makes these calls +EV. In a "
             "freezeout they would be folds.*",
             "*Coverage pressure should tighten Hero past the naive pot-odds "
             "call.*"),
            ('jammer',
             "(a) Shove correct WITH the bounty — −EV without",
             "(b) Shove correct WITHOUT the bounty — −EV with it",
             "*The bounty's added fold-equity value tips these shoves +EV.*",
             "*The bounty makes the shove worse — rare.*"),
        ]:
            _ga = [s for s in _flips_a if s.get('role') == grp]
            _gb = [s for s in _flips_b if s.get('role') == grp]
            _tbl = _caller_table if grp == 'caller' else _jammer_table
            if _ga:
                _tbl(_ga, lab_a, note_a)
            if _gb:
                _tbl(_gb, lab_b, note_b)

        # B244 (Ron review 2026-05-26): multiway bounty all-ins. The flip
        # analysis above is HU-only by construction; multiway bounty pots used
        # to vanish silently as "out of scope". List them so every bounty
        # all-in is at least visible in the PKO section, with the true
        # multiway equity from the gem_eai_equity engine.
        _mw_bounty = [h for h in (s.get('eai', {}).get('hands', []) or [])
                      if (h.get('n_allin') or 2) >= 3
                      and 'BOUNTY' in (h.get('format') or '').upper()]
        if _mw_bounty:
            # Item 8: proper bold (not Markdown ** inside HTML attr) + cap 15
            _mw_total = len(_mw_bounty)
            _mw_cap = 15
            _mw_show = sorted(_mw_bounty,
                              key=lambda x: -(x.get('hero_equity') or 0))[:_mw_cap]
            _trunc_note = (f" (showing {_mw_cap} of {_mw_total})"
                           if _mw_total > _mw_cap else "")
            doc.w(f'<span data-tip="Bounty all-ins with 3+ players. Multiway '
                  f'bounty-cEV (coverage chains, side-pot bounties) is a '
                  f'documented refinement — listed with true multiway equity '
                  f'so no bounty all-in is invisible. Per-hand verdicts in '
                  f'Strategic Leaks / Mistakes."><strong>Multiway bounty all-ins</strong> '
                  f'({_mw_total} — out of HU-flip scope){_trunc_note}</span>')
            doc.w("")
            doc.w("| Hand | Cards | Players | Hero eq | Result |")
            doc.w("|---|---|---|---|---|")
            for h in _mw_show:
                # B-B: register citation for multiway bounty hands
                _state._record_citation(h.get('id', ''))
                _hid = h.get('id', '')[-8:]
                _ref = (f"[`{_hid}`](#sec-app-hand-{_hid}) • "
                        f"{(h.get('tournament') or '')[:26]}")
                _eq = h.get('hero_equity')
                _eqs = f"{_eq*100:.0f}%" if _eq is not None else "—"
                _won = h.get('won')
                _res = ('won' if _won is True else
                        'chop' if _won == 'chop' else 'lost')
                doc.w(f"| {_ref} | {_cards_str_to_pills(h.get('hero','—'))} | "
                      f"{h.get('n_allin','?')} | {_eqs} | {_res} |")
            doc.w("")

        if not _n_flip:
            doc.w('👍 <span data-tip="The jammer path compares the shove '
                  'against folding (EV 0). For a player who covers, a preflop '
                  'shove with dead money + fold equity clears 0 in almost '
                  'every spot — so a shove-vs-fold flip is rare by '
                  'construction. A sharper test — shove vs. the best '
                  'alternative (min-raise / smaller shove) — is the next '
                  'refinement.">**No flips this session** — the bounty did '
                  'not change a decision.</span>')
            doc.w("")


def _emit_sub_opponent_archetype(doc, s, rd, hands):
    # ---- IV.8 Opponent Archetype Mirror (B167, spec §3) ----
    doc.subsection("sec-5-8", "S5.8 Opponent Archetype Mirror",
                   "population tendencies grouped by playing style, not a flat pool average")
    doc.w("**A flat pool average** hides that the right exploit differs by "
          "villain type. Read each row by the archetype the seat actually fits.")
    doc.w("")

    # Show observed archetype distribution from this session
    _opp = s.get('opponent_profiles', {}) or {}
    if _opp:
        from collections import Counter
        _arch_dist = Counter(v.get('archetype', '?') for v in _opp.values())
        _dist_str = ' · '.join(f"{a}: {n}" for a, n in _arch_dist.most_common())
        doc.w(f"*This session's opponent mix: {_dist_str}*")
        doc.w("")

    # Reference table — 10 archetypes with 4D profile + exploit
    try:
        from gem_opponent_profiler import ARCHETYPES as _ARCH_DEFS
    except ImportError:
        _ARCH_DEFS = {}
    if _ARCH_DEFS:
        # B-V10 FEATURE: per-archetype Hero performance columns.
        # For each archetype, count hands where Hero won/lost vs that type
        # and collect hand IDs for drill-down popups.
        from collections import defaultdict as _ddict
        _arch_perf = _ddict(lambda: {'won_ids': [], 'lost_ids': [], 'n': 0})
        # B159 v2: use per-hand villain_archetype and primary_villain.archetype
        # directly — these are populated by the analyzer on ~450+ hands.
        # The opponent_profiles dict (keyed by hash) may be empty.
        _opp_arch_by_hash = {}
        for _vhash, _vp in (_opp or {}).items():
            _opp_arch_by_hash[_vhash] = _vp.get('archetype', '?')
        _mirror_match_count = 0
        for h in hands:
            if not h.get('vpip'):
                continue
            _matched_archs = set()
            # Primary source: per-hand villain_archetype (set by analyzer)
            _va_direct = h.get('villain_archetype', '')
            if _va_direct and _va_direct != '?':
                _matched_archs.add(_va_direct)
            # Secondary: primary_villain.archetype
            _pva = (h.get('primary_villain') or {}).get('archetype', '')
            if _pva and _pva != '?':
                _matched_archs.add(_pva)
            # Tertiary: opponent_profiles by hash (if populated)
            _pvh = (h.get('primary_villain') or {}).get('hash', '')
            if _pvh and _pvh in _opp_arch_by_hash:
                _va = _opp_arch_by_hash[_pvh]
                if _va and _va != '?':
                    _matched_archs.add(_va)
            # Quaternary: villain_identity archetype
            _vi_arch = (h.get('villain_identity') or {}).get('archetype', '')
            if _vi_arch and _vi_arch != '?':
                _matched_archs.add(_vi_arch)
            for _va in _matched_archs:
                _arch_perf[_va]['n'] += 1
                _mirror_match_count += 1
                if h.get('id'):
                    if h.get('won') or (h.get('net_bb', 0) > 0):
                        _arch_perf[_va]['won_ids'].append(h['id'])
                    elif h.get('net_bb', 0) < 0:
                        _arch_perf[_va]['lost_ids'].append(h['id'])
        if _mirror_match_count == 0 and len(hands) > 50:
            # Fallback: check if any hand has the fields — helps debug
            _sample_fields = set()
            for h in hands[:20]:
                for k in ('villain_archetype', 'primary_villain', 'villain_identity'):
                    v = h.get(k)
                    if v and v != '?' and v != {}:
                        _sample_fields.add(f"{k}={type(v).__name__}")
            if _sample_fields:
                doc.w(f"*(Mirror debug: 0 matches from {len(hands)} hands. "
                      f"Fields found: {', '.join(_sample_fields)})*")
            else:
                doc.w(f"*(Mirror: no archetype data found on hands — "
                      f"opponent profiler may not have run)*")
        # Also count misplays per archetype
        _misplay_by_arch = _ddict(list)
        for mp in (s.get('archetype_misplays') or []):
            _ma = mp.get('archetype', '')
            if _ma:
                _misplay_by_arch[_ma].append(mp.get('hand_id', ''))

        doc.w("| Archetype | Dimensions | #Hands | Won | Lost | Misplays | Exploit |")
        doc.w("|---|---|---|---|---|---|---|")
        for _ak in ['NIT', 'CALLING_STATION', 'FISH', 'WHALE', 'MANIAC',
                     'LAG', 'TAG', 'SOLID_REG', 'DANGER_REG', 'FUN_REC']:
            _ad = _ARCH_DEFS.get(_ak, {})
            _perf = _arch_perf.get(_ak, {'won_ids': [], 'lost_ids': [], 'n': 0})
            _n_won = len(_perf['won_ids'])
            _n_lost = len(_perf['lost_ids'])
            _n_hands = _perf['n'] or (_n_won + _n_lost)
            # Won cell — hand-list popup (sample up to 5)
            if _n_won:
                _w_str = ','.join(_perf['won_ids'][:5])
                _won_cell = (f'<a class="hand-list-trigger" href="#" '
                             f'data-hids="{_w_str}" '
                             f'data-list-title="Won vs {_ad.get("label",_ak)} ({_n_won})">'
                             f'{_n_won}</a>')
            else:
                _won_cell = '0'
            # Lost cell — hand-list popup (sample up to 10)
            if _n_lost:
                _l_str = ','.join(_perf['lost_ids'][:10])
                _lost_cell = (f'<a class="hand-list-trigger" href="#" '
                              f'data-hids="{_l_str}" '
                              f'data-list-title="Lost vs {_ad.get("label",_ak)} ({_n_lost})">'
                              f'{_n_lost}</a>')
            else:
                _lost_cell = '0'
            # Misplays cell
            _mp_ids = _misplay_by_arch.get(_ak, [])
            if _mp_ids:
                _mp_str = ','.join([h for h in _mp_ids if h][:10])
                _mp_cell = (f'<a class="hand-list-trigger" href="#" '
                            f'data-hids="{_mp_str}" '
                            f'data-list-title="Misplays vs {_ad.get("label",_ak)} ({len(_mp_ids)})">'
                            f'{len(_mp_ids)}</a>') if _mp_str else str(len(_mp_ids))
            else:
                _mp_cell = '—'
            doc.w(f"| {_ad.get('emoji','')} **{_ad.get('label',_ak)}** | "
                  f"_{_ad.get('dimensions','')}_  | "
                  f"{_n_hands} | {_won_cell} | {_lost_cell} | {_mp_cell} | "
                  f"{_ad.get('exploit','')} |")
        doc.w("")
    else:
        doc.w("*(Archetype reference table unavailable)*")
        doc.w("")

    # Misplays vs archetypes (real hands from this session)
    _misplays = s.get('archetype_misplays', []) or []
    if _misplays:
        doc.w(f"**Misplays vs villain archetypes** — {len(_misplays)} hand(s) "
              f"where Hero's line was wrong for the villain type:")
        doc.w("")
        doc.w("| Hand | Villain Type | Why this type | Misplay | What to do instead |")
        doc.w("|---|---|---|---|---|")
        hands_by_id_local = {h.get('id', ''): h for h in hands}
        for mp in _misplays[:15]:
            hid = mp.get('hand_id', '')
            h_full = hands_by_id_local.get(hid, {})
            ref = _hand_ref(h_full) if h_full else f"`{hid[-8:]}`"
            arch_label = mp.get('archetype_label', '?')
            # Villain type with stats-based reasoning
            v_reason = mp.get('villain_reason', '')
            # Make villain type a clickable link to their example hands
            v_hids = mp.get('villain_hids', [])
            if v_hids:
                _v_str = ','.join(v_hids[:10])
                arch_cell = (f'<a class="hand-list-trigger" href="#" '
                            f'data-hids="{_v_str}" '
                            f'data-list-title="{arch_label} — example hands showing this pattern">'
                            f'{arch_label}</a>')
            else:
                arch_cell = arch_label
            doc.w(f"| {ref} | {arch_cell} | "
                  f"_{v_reason[:60]}_ | "
                  f"{mp.get('misplay_type', '—')} | "
                  f"{mp.get('what_to_do', '—')} |")
        doc.w("")
    else:
        doc.w("*No archetype-specific misplays detected this session — Hero's "
              "lines were consistent with correct exploit adjustments.*")
        doc.w("")

    # v8.8.3: legacy text inference for pre-v8.8.3 exploit dicts missing exploit_read_label
    def _infer_read_label_from_text(exp):
        """Infer Matrix read label from evidence_text keywords (legacy-only).

        Order matters — check specific patterns first to avoid false matches.
        E.g. 'bluffed sticky' should match Sticky, not Aggressive.
        """
        _et = (exp.get('evidence_text', '') or '').lower()
        # Check sticky first — "bluffed sticky" contains "bluff" but is a sticky exploit
        if 'sticky' in _et or 'thin value' in _et or 'calls too wide' in _et:
            return 'Sticky Passive'
        if 'overfold' in _et or 'nit' in _et or 'steal' in _et:
            return 'Nit / Rock'
        if 'passive' in _et or 'pivot' in _et:
            return 'Loose Passive'
        if 'aggro' in _et or 'maniac' in _et or '3bet' in _et or 'bluff' in _et:
            return 'Aggressive'
        return ''

    # v8.7.0 PR5: Opponent Adjustment Matrix (spec §16)
    _vi = s.get('villain_intel', {}) or {}
    _read_states = _vi.get('read_states', {}) or {}
    _exploit_opps = _vi.get('exploit_opportunities', []) or []
    _all_atoms = _vi.get('evidence_atoms', []) or []
    if _read_states:
        doc.subsection("sec-5-9", "S5.9 Opponent Adjustment Matrix",
                       "what reads emerged, how Hero adjusted, and what to practice")
        doc.w("")
        doc.w("*The Archetype Mirror above classifies villains by broad population style "
              "(10 types from session stats). This matrix shows **evidence-backed reads** "
              "from this session's actual observations — which villains showed notable "
              "behavior, and whether Hero adjusted correctly.*")
        doc.w("")

        # Group by primary read
        from collections import defaultdict as _dd2
        _by_read = _dd2(lambda: {'villains': [], 'tagging': 0, 'exploit_opps': 0,
                                  'missed': 0, 'good': 0, 'evidence_hids': set(),
                                  'display': ''})
        # v8.8.6: normalise labels to canonical (no emoji) for consistent grouping.
        # primary_read may still have emoji prefix; exploit_read_label is now canonical.
        def _canon(raw):
            if raw and not raw[0].isalpha():
                return raw.split(' ', 1)[1] if ' ' in raw else raw
            return raw
        for _vk, _rs in _read_states.items():
            _pr_raw = _rs.get('primary_read', '❓ Unknown')
            _pr = _canon(_pr_raw)
            _by_read[_pr]['villains'].append(_vk)
            _by_read[_pr]['tagging'] += _rs.get('n_evidence', 0)
            _by_read[_pr]['evidence_hids'].update(_rs.get('evidence_hand_ids', []))
            if not _by_read[_pr]['display']:
                _by_read[_pr]['display'] = _pr_raw

        # v8.8.3: group exploits by exploit_read_label (stamped at detection time)
        # instead of villain's overall primary_read (which disagrees with detector).
        _n_unknown_excluded = 0
        for _exp in _exploit_opps:
            # Primary: use exploit_read_label stamped by detector
            _epr = _canon(_exp.get('exploit_read_label', ''))
            # Fallback chain for legacy data (pre-v8.8.3)
            if not _epr or _epr == 'Unknown':
                _epr = _canon(_infer_read_label_from_text(_exp))
                if _epr:
                    _exp['read_label_source'] = 'legacy_text_inference'
            if not _epr or _epr == 'Unknown':
                # Last resort: villain's primary_read
                _evk = _exp.get('villain_key', '')
                _ers = _read_states.get(_evk, {})
                _epr = _canon(_ers.get('primary_read', '❓ Unknown'))
            # Exclude Unknown from Matrix counts
            if _epr == 'Unknown' or not _epr:
                _n_unknown_excluded += 1
                continue
            _by_read[_epr]['exploit_opps'] += 1
            if _exp.get('auto_verdict') == 'missed_exploit':
                _by_read[_epr]['missed'] += 1
            elif _exp.get('auto_verdict') == 'good_exploit':
                _by_read[_epr]['good'] += 1

        # Table — emit as raw HTML so hand-list-trigger links work
        doc.w("<div class='table-shell' data-mobile-mode='scroll' style='--mobile-table-min-width:900px'><div class='table-scroll'><table class='data-table'>")
        doc.w("<tr><th>Read</th><th>Tagging</th>"
              "<th><span data-tip='Total detected exploit adjustment spots where "
              "villain read should have influenced Hero&#39;s action. "
              "Exploit Opps = Missed + Good.'>Exploit Opps</span></th>"
              "<th><span data-tip='Spots where Hero failed to adjust to this read.'>Missed</span></th>"
              "<th><span data-tip='Spots where Hero correctly adjusted to this read.'>Good</span></th>"
              "<th>Evidence</th><th>Lesson</th></tr>")
        for _pr, _rd in sorted(_by_read.items(), key=lambda kv: -kv[1]['tagging']):
            _nv = len(_rd['villains'])
            _ne = len(_rd['evidence_hids'])
            _lesson = ''
            if 'Sticky' in _pr:
                _lesson = 'Value thin. Stop bluffing.'
            elif 'Loose' in _pr:
                _lesson = 'Value-bet wide. Simplify.'
            elif 'Nit' in _pr or 'Tight' in _pr:
                _lesson = 'Steal blinds. Fold to aggression.'
            elif 'Aggressive' in _pr:
                _lesson = 'Trap with strength. Widen call-downs.'
            # v8.8.6: _pr is canonical (no emoji); use display label for table
            _pr_display = _rd.get('display') or _pr
            # v8.7.3: use read-level drilldown instead of generic hand-list
            # _pr is already canonical — use directly as JS function arg
            _pr_label_clean = _pr
            _ev_link = (f'<a href="#" onclick="openReadEvidence(\'{_html_escape(_pr_label_clean)}\');'
                        f'return false;" style="cursor:pointer">'
                        f'{_nv} villains / {_ne} hands</a>')
            doc.w(f"<tr><td data-label='Read'>{_pr_display}</td>"
                  f"<td data-label='Tagging'>{_rd['tagging']}</td>"
                  f"<td data-label='Exploit Opps'>"
                  f"{'<a href=\"#\" onclick=\"openExploitDrilldown(&#39;' + _html_escape(_pr_label_clean) + '&#39;,&#39;all&#39;);return false;\" style=\"cursor:pointer\">' + str(_rd['exploit_opps']) + '</a>' if _rd['exploit_opps'] > 0 else '0'}"
                  f"</td>"
                  f"<td data-label='Missed'>"
                  f"{'<a href=\"#\" onclick=\"openExploitDrilldown(&#39;' + _html_escape(_pr_label_clean) + '&#39;,&#39;missed&#39;);return false;\" style=\"cursor:pointer\">' + str(_rd['missed']) + '</a>' if _rd['missed'] > 0 else '0'}"
                  f"</td>"
                  f"<td data-label='Good'>"
                  f"{'<a href=\"#\" onclick=\"openExploitDrilldown(&#39;' + _html_escape(_pr_label_clean) + '&#39;,&#39;good&#39;);return false;\" style=\"cursor:pointer\">' + str(_rd['good']) + '</a>' if _rd['good'] > 0 else '0'}"
                  f"</td>"
                  f"<td data-label='Evidence'>{_ev_link}</td>"
                  f"<td data-label='Lesson'>{_lesson}</td></tr>")
        doc.w("</table></div></div>")
        # v8.8.3: surface excluded Unknown count
        if _n_unknown_excluded > 0:
            doc.w(f"\n*{_n_unknown_excluded} exploit candidate(s) excluded from "
                  f"Matrix (insufficient read confidence).*")
        doc.w("")

        # v8.8.1: Villain Evidence Dossier (S5.9b).
        # The matrix groups by read TYPE and hides actual hands behind a JS
        # drilldown.  This section surfaces the concrete example hands inline
        # — at least 3 per villain where they exist.  Render-layer only.
        _atoms_by_v = _vi.get('atoms_by_villain', {}) or {}
        _aliases = _vi.get('villain_aliases', {}) or {}
        _MIN_EV = 3            # only dossier villains with >= this many atoms
        _MAX_VILLAINS = 30     # cap section size
        _MAX_ATOMS_SHOWN = 6   # show up to this many example lines per villain
        _dossier = sorted(
            ((vk, ats) for vk, ats in _atoms_by_v.items() if len(ats) >= _MIN_EV),
            key=lambda kv: -len(kv[1]))[:_MAX_VILLAINS]
        if _dossier:
            doc.subsection("sec-5-9b", "S5.9b Villain Evidence Dossier",
                           f"example hands per villain — the actual reads behind the matrix "
                           f"(≥{_MIN_EV} evidence hands)")
            doc.w("")
            doc.w("*For each villain with at least three evidence hands this session, "
                  "the specific hands and what they did. Click a hand ID to open it. "
                  "Tagging evidence describes the villain's action — it is not "
                  "necessarily a Hero mistake.*")
            doc.w("")
            for _vk, _ats in _dossier:
                _al = _aliases.get(_vk, {}) or {}
                _disp = _al.get('display') or _al.get('alias') or (_ats[0].get('villain_alias') if _ats else '') or _vk
                _rs = _read_states.get(_vk, {}) or {}
                _read = _rs.get('primary_read', '')
                _conf = _rs.get('confidence', '')
                _n = len(_ats)
                # all evidence hand ids for this villain (deduped, order-preserving)
                _seen = set(); _hids = []
                for _a in _ats:
                    _hid = _a.get('hand_id')
                    if _hid and _hid not in _seen:
                        _seen.add(_hid); _hids.append(_hid)
                _hids_str = ','.join(_hids[:20])
                _head_link = (f'<a class="hand-list-trigger" href="#" '
                              f'data-hids="{_hids_str}" '
                              f'data-list-title="{_html_escape(str(_disp))} — all {_n} evidence hands">'
                              f'open all {_n}</a>')
                doc.w("<div class='opponent-context' style='margin:10px 0'>")
                doc.w(f"<div class='oc-heading'>{_html_escape(str(_disp))}"
                      f"{(' &middot; ' + _html_escape(str(_read))) if _read else ''}"
                      f"{(' &middot; ' + _html_escape(str(_conf)) + ' conf') if _conf else ''}"
                      f" &middot; {_head_link}</div>")
                # group shown atoms by street
                _ds_by_street = {}
                for _a in _ats[:_MAX_ATOMS_SHOWN]:
                    _ds_by_street.setdefault(_a.get('street', 'preflop'), []).append(_a)
                for _st in ('preflop', 'flop', 'turn', 'river'):
                    if _st not in _ds_by_street:
                        continue
                    for _a in _ds_by_street[_st]:
                        _hid = _a.get('hand_id', '')
                        _sig = _a.get('signal', '')
                        _sig_label = (_a.get('signal_label')
                                      or (_sig.replace('_', ' ').title() if _sig else ''))
                        _badge = _a.get('badge', 'note')
                        _label = _a.get('label', '')
                        _text = _a.get('evidence_text', '')
                        _dtitle_attr = f' title="{_html_escape(str(_text))}"' if _text else ''
                        _hid_link = (f'<a class="hand-list-trigger" href="#" '
                                     f'data-hids="{_hid}" '
                                     f'data-list-title="{_html_escape(str(_disp))} — {_st}">'
                                     f'{_hid}</a>') if _hid else ''
                        doc.w(f"<p style='margin:3px 0'><span class='vi-badge {_badge}'{_dtitle_attr}>"
                              f"{_label}{(' &middot; ' + _sig_label) if _sig_label else ''}</span> "
                              f"<strong style='font-size:11px;text-transform:uppercase;"
                              f"color:#6a4d00'>{_st}</strong> "
                              f"{_hid_link} &mdash; {_html_escape(str(_text))}</p>")
                if _n > _MAX_ATOMS_SHOWN:
                    doc.w(f"<p style='font-size:11px;color:#94a3b8;margin-top:2px'>"
                          f"<em>+{_n - _MAX_ATOMS_SHOWN} more — use “open all” above.</em></p>")
                doc.w("</div>")
            doc.w("")


def _emit_section_xii(doc):
    doc.section("sec-16", "S16. Glossary", "")
    glossary = [
        ("VPIP", "voluntarily-put-in-pot percentage (any voluntary call/raise preflop)"),
        ("PFR", "pre-flop raise percentage"),
        ("F2-3B", "fold-to-3bet (after Hero opens, faced 3-bet, folded)"),
        ("WTSD/WSD", "went-to / won-at showdown (voluntary hands only)"),
        ("WWSF", "won-when-saw-flop"),
        ("Non-SD Win", "hands won without showdown"),
        ("SD Aggressor", "aggressor's win % at showdown"),
        ("AF", "aggression factor — postflop (Bets+Raises) / Calls"),
        ("AFq", "aggression frequency — postflop B+R / (B+R+C+F)"),
        ("SRP/3BP/4BP", "single-raised pot / 3-bet pot / 4-bet pot"),
        ("All-Ins", "all-in equity variance vs expected — flat all-in equity check"),
        ("OE/Gutter", "open-ended (8 outs) / gutshot (4 outs) straight draw"),
        ("TPTK/TPGK/TPNK", "top pair top/good/no kicker"),
        ("BvB", "blind vs blind (SB vs BB)"),
        ("PKO", "Progressive Knockout (bounty) tournament format"),
    ]
    doc.w("| Term | Definition |")
    doc.w("|---|---|")
    for k, v in glossary:
        doc.w(f"| {k} | {v} |")
    doc.w("")
    # v7.67: coaching-rule codes are rendered from the registry
    # (coaching_rules.json) so every code carries its source + a concise
    # plain-language meaning. Replaces the prior hand-maintained J29/J44/K
    # rows — which mis-attributed J29 (a Dave rule) to Jaka.
    _codes = _coach.all_codes()
    if _codes:
        _rules = _coach.load_rules()
        doc.w("**Coaching rule codes** — source and plain-language meaning "
              "(`coaching_rules.json`; prefix convention: J = Dave, N = Amit, "
              "K = Jaka, L = leak pattern):")
        doc.w("")
        doc.w("| Code | Source | What it means |")
        doc.w("|---|---|---|")
        for _c in _codes:
            doc.w(f"| {_c} | {_coach.rule_source(_c)} | "
                  f"{_rules[_c].get('label', '')} |")
        doc.w("")


