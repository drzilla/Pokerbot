"""Section XIII emitter."""

from gem_report_draft import _state
from gem_report_draft._helpers import (_wilson_ci, _clr, _clr_min, _clr_naive,
    _pctc, _stat_signal, _verdict_ci, _verdict_pct, _hand_ref, _hand_ref_short,
    _xref, _stat_row, _stat_row_pct, _aim_lookup_from_watchlist, _back_to_kpis,
    _compact_range, _run_emoji, _outcome_label, _CI_Z_DEFAULT, _MIN_N_FOR_SIGNAL,
    _RANK_ORD, _break_at_sentences, _href, _emit_correct_ranges)
from gem_report_draft._html import (Doc, _card_html, _cards_html,
    _cards_str_to_pills, _cards_text_to_pills, _real_cards_pills, _md_inline, _html_escape,
    _sort_cards_desc, _describe_made_hand, _SUIT_HTML, _RANK_VALUES, _SUIT_VALUES)
from gem_report_draft._hand_grid import (_render_hand_grid_table,
    _key_decision_action_class, _pick_key_action_idx, _hero_actions_by_street_from_app,
    _hero_action_verbs_by_street_from_app)
from gem_report_draft._blocks import (raw_reference_block,)

import gem_made_hands as mh

def _emit_section_xiii(doc, s, rd, hands):
    doc.section("sec-17", "S17. Full Deviation Lists",
                "every flagged decision — drill-down reference for audits")

    # Item 27 (Ron 2026-05-11): XIII is reference-only — the body sections
    # (III.x, IV.x, V.x, VII.x) already surface deviations contextually with
    # the metric they belong to. XIII exists for when Ron wants the COMPLETE
    # list (e.g. "show me ALL 18 Wide Open flags I made this session"). Frame
    # it that way at the top so the user knows they probably don't need it.
    doc.w("*This section is the **complete audit log** — every deviation flag "
          "across every detector, grouped by position or opener. The body "
          "sections (III.x, IV.x, V.x, VII.x) already surface the same hands "
          "contextually with their metric. Use XIII only when you want to see "
          "the full list for one bucket (e.g. \"every Wide Open at CO this "
          "session\") — otherwise the body coverage is sufficient.*")
    doc.w("")

    # v7.39 — B32: chart sanity callout. If the analyzer detected and augmented
    # any corrupted charts, surface that here so deviations referencing those
    # charts can be evaluated in context.
    sanity_report = s.get('range_sanity_report', {}) or {}
    if sanity_report:
        # B114 (Ron 2026-05-20): only charts that actually augmented content
        # carry actionable info. Charts flagged purely for OCR-noise column
        # clusters (4o/2o) with augmented_count=0 and no missing sample
        # produced 24 rows of "+0 | (empty) | noise" — zero signal. Render
        # the detail table only for charts where augmentation happened;
        # otherwise collapse to a one-line summary.
        augmented = {k: v for k, v in sanity_report.items()
                     if v.get('augmented') or (v.get('augmented_count') or 0) > 0
                     or v.get('missing_before')}
        noise_only = len(sanity_report) - len(augmented)
        if augmented:
            doc.w("⚠️ **Chart sanity (B32 mitigation):** The OCR-extracted range "
                  "file contains corruption in some PUSH/REJAM/OPEN charts "
                  "(missing premium hands). This run augmented "
                  f"**{len(augmented)} chart(s)** with missing anchor content so "
                  "detectors don't fail silently. Affected deviations are marked "
                  "`⚠️ chart-augmented` inline and any CLEAR Wide-* flags from "
                  "augmented charts have been downgraded to MARGINAL.")
            doc.w("")
            _cs_hdr = "| Chart | Family | Hands Added | Sample Missing | OCR Noise |"
            _cs_sep = "|---|---|---|---|---|"
            _cs_rows = []
            for chart_name in sorted(augmented.keys()):
                info = augmented[chart_name]
                missing = info.get('missing_before', [])
                preview = ', '.join(missing[:6])
                if len(missing) > 6:
                    preview += f' …+{len(missing)-6}'
                noise = info.get('ocr_noise_patterns', []) or []
                noise_label = ', '.join(noise) if noise else '—'
                _cs_rows.append(f"| `{chart_name}` | {info.get('family','?')} | "
                      f"+{info.get('augmented_count','?')} | {preview or '—'} | {noise_label} |")
            _cs_blk = raw_reference_block("xiii-chart-sanity", _cs_hdr, _cs_sep, _cs_rows)
            doc.write_block(_cs_blk)
            doc.w("")
            if noise_only:
                doc.w(f"*+{noise_only} further chart(s) flagged for OCR-noise "
                      "column clusters only — no augmentation needed, detectors "
                      "unaffected.*")
                doc.w("")
        else:
            doc.w(f"⚠️ **Chart sanity (B32):** {len(sanity_report)} chart(s) "
                  "flagged for OCR-noise column clusters (e.g. 4o/2o artifacts). "
                  "**0 required content augmentation** — no premium hands were "
                  "missing, so detectors ran on clean chart content this "
                  "session, and no deviations are chart-augmented.")
            doc.w("")
    # Position ordering for grouped tables (matches IV.1 Per-Position Profile order)
    POS_ORDER = ['UTG', 'UTG+1', 'UTG+2', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB']

    def _by_position(devs, key='pos'):
        """Group dev list by position, preserving POS_ORDER. Within each
        position group, sort by stack depth so similar-depth deviations
        cluster visually (B49 Ron 2026-05-11 — partial fix for
        repeat-row grouping request; full merge-cells would require a
        bigger table-renderer refactor)."""
        out = {}
        for d in devs:
            p = d.get(key) or d.get('position', '?')
            out.setdefault(p, []).append(d)
        # B-V10: sort by confidence DESC (CLEAR first, then MARGINAL) then
        # stack_bb ASC so similar-depth deviations cluster visually.
        _conf_rank = {'CLEAR': 0, 'clear': 0, 'MARGINAL': 1, 'marginal': 1}
        for p in out:
            out[p].sort(key=lambda d: (
                _conf_rank.get((d.get('confidence') or '').upper(), 2),
                d.get('stack_bb') or 0, d.get('id') or ''))
        ordered = []
        for p in POS_ORDER:
            if p in out:
                ordered.append((p, out[p]))
        # Any position not in POS_ORDER (defensive)
        for p in sorted(out):
            if p not in POS_ORDER:
                ordered.append((p, out[p]))
        return ordered

    def _row_html(d, *, with_opener=False):
        href = _href(d, s['_hands_by_id'])
        chart = d.get('chart', '—')
        sz = d.get('chart_size', '?')
        bound = d.get('chart_summary', '—') or '—'
        chart_label = f"`{chart}` (n={sz})" if chart != '—' else '—'
        # v7.39 — B32: chart-augmented marker. If the analyzer's sanity check
        # patched this chart's missing premium content, mark it inline so Ron
        # can spot deviations that fired against fixed-up charts vs raw OCR.
        if d.get('chart_augmented'):
            chart_label = f"⚠️ {chart_label} (chart-augmented +{d.get('chart_augmented_count', '?')})"
        sev = d.get('severity', d.get('confidence', '—'))
        # v8.8.6 S1: satellite/ICM caveat — don't show plain CLEAR for satellite hands
        _d_fmt_h = (d.get('format') or '').upper()
        if _d_fmt_h == 'SATELLITE' and sev == 'CLEAR':
            sev = 'CLEAR chipEV-only · SAT/ICM caveat'
        if d.get('confidence_downgrade_reason'):
            sev = f"{sev} ⚠️"
        # v7.39 — MDA v7.5 overlay column. When this deviation maps to an MDA
        # population-exploit recommendation, surface the rec_id + EV-per-event.
        mda_note = '—'
        ovl = d.get('mda_overlay')
        if ovl:
            mda_note = (f"`{ovl['rec_id']}` {ovl['ev_bb']:+.1f} BB "
                        f"({ovl['confidence']})")
        if with_opener:
            return (f"| {href} | {_real_cards_pills(d, s['_hands_by_id'])} | "
                    f"{d.get('opener_pos','—')} | {sev} | {chart_label} | {bound} | {mda_note} |")
        return (f"| {href} | {_real_cards_pills(d, s['_hands_by_id'])} | {sev} | {chart_label} | {bound} | {mda_note} |")

    def _emit_table_compact(headers, rows, doc=doc, block_id=None):
        """B92 (v7.58, Ron 2026-05-18): emit a markdown table, dropping any
        column whose values are all empty/'—' across rows. Different reports
        may have data in different columns; this keeps each report's tables
        focused.

        headers: list[str] — column headers (no pipes)
        rows: list[list[str]] — row data (same length as headers)
        block_id: str — optional block id for raw_reference_block
        """
        if not rows:
            return
        n_cols = len(headers)
        # Determine which columns are non-empty (any row has data ≠ '—'/'')
        col_has_data = [False] * n_cols
        for row in rows:
            for i, cell in enumerate(row[:n_cols]):
                if cell and cell.strip() not in ('—', '-', '', 'N/A'):
                    col_has_data[i] = True
        # Keep cols that have data OR are the Hand Reference (always col 0)
        keep_idx = [0] + [i for i in range(1, n_cols) if col_has_data[i]]
        kept_headers = [headers[i] for i in keep_idx]
        hdr = '| ' + ' | '.join(kept_headers) + ' |'
        sep = '|' + '|'.join(['---'] * len(keep_idx)) + '|'
        tbl_rows = []
        for row in rows:
            cells = [row[i] if i < len(row) else '—' for i in keep_idx]
            tbl_rows.append('| ' + ' | '.join(cells) + ' |')
        blk = raw_reference_block(block_id or "xiii-compact", hdr, sep, tbl_rows)
        doc.write_block(blk)

    def _row_data(d, *, with_opener=False):
        """Same fields as _row_html but returns list of cells (for B92)."""
        href = _href(d, s['_hands_by_id'])
        chart = d.get('chart', '—')
        sz = d.get('chart_size', '?')
        bound = d.get('chart_summary', '—') or '—'
        chart_label = f"`{chart}` (n={sz})" if chart != '—' else '—'
        if d.get('chart_augmented'):
            chart_label = f"⚠️ {chart_label} (chart-augmented +{d.get('chart_augmented_count', '?')})"
        sev = d.get('severity', d.get('confidence', '—'))
        # v8.8.6 S1: satellite/ICM caveat — don't show plain CLEAR for satellite hands
        _d_fmt_r = (d.get('format') or '').upper()
        if _d_fmt_r == 'SATELLITE' and sev == 'CLEAR':
            sev = 'CLEAR chipEV-only · SAT/ICM caveat'
        if d.get('confidence_downgrade_reason'):
            sev = f"{sev} ⚠️"
        mda_note = '—'
        ovl = d.get('mda_overlay')
        if ovl:
            # B93 (v7.58, Ron 2026-05-18): de-jargon MDA notes. Render with
            # a human-readable summary if available, fall back to rec_id only.
            ev_str = f"{ovl['ev_bb']:+.1f} BB"
            conf = ovl.get('confidence', '?')
            short_label = ovl.get('short_label') or ovl.get('rec_id', '?')
            mda_note = f"{short_label} · {ev_str} ({conf})"
        cards_html = _real_cards_pills(d, s['_hands_by_id'])
        if with_opener:
            return [href, cards_html, d.get('opener_pos','—'), sev, chart_label, bound, mda_note]
        return [href, cards_html, sev, chart_label, bound, mda_note]

    devs = s.get('preflop_deviations', [])

    # XIII.1 All Wide Opens — grouped by Hero position
    wide_opens = [d for d in devs if d.get('type') == 'Wide Open']
    doc.subsection("sec-17-1", "S17.1 All Wide Opens",
                   f"{len(wide_opens)} flagged opens above target tier (grouped by position)")
    doc.w("↩ [Back to S4.2 Out-of-Bound Leak Discovery](#sec-4-2)")
    doc.w("")
    if not wide_opens:
        doc.w("👍 None flagged.")
        doc.w("")
    else:
        for pos, group in _by_position(wide_opens, key='pos'):
            anchor = f"sec-17-1-{pos.lower().replace('+','plus')}"
            doc.w(f"<<ANCHOR:{anchor}>>")
            doc.w(f"<<ANCHOR_COMPAT:sec-xiii-1-{pos.lower().replace('+','plus')}>>")
            doc.w(f"#### S17.1 — Wide Opens at {pos} ({len(group)})")
            doc.w("")
            _emit_table_compact(
                ['Hand Reference', 'Cards', 'Severity', 'Chart', 'Chart Includes', 'MDA Note'],
                [_row_data(d) for d in group],
                block_id=f"xiii1-wide-opens-{pos.lower().replace('+','plus')}")
            doc.w("")
            _emit_correct_ranges(doc, group, s.get('_dev_charts', {}))
            doc.w(f'<<REVIEWROW|sub|{anchor}|Wide Opens at {pos}>>')

    # XIII.2 All Wide BB Defends — grouped by OPENER position (the relevant axis here,
    # since "Wide BB Defend vs CO" and "Wide BB Defend vs UTG" are different leaks)
    wide_bb = [d for d in devs if 'BB' in d.get('type', '') and 'wide' in d.get('type', '').lower()]
    doc.subsection("sec-17-2", "S17.2 All Wide BB Defends",
                   f"{len(wide_bb)} flagged BB defends — grouped by opener position (D9)")
    if not wide_bb:
        doc.w("👍 None flagged.")
        doc.w("")
    else:
        doc.w("*Hero is always BB in this section — column shows the OPENER's position "
              "(who Hero defended against). B243 (Ron review 2026-05-26): hands are "
              "now grouped by the **effective** opener position — a raw 'UTG' at a "
              "7-handed table opens as wide as an 8-max UTG+1, so it is a different "
              "defend than vs a true 8-max UTG. The raw seat + table size are kept in "
              "the Opener / Tbl columns.*")
        doc.w("")
        # Add 'position' = 'BB' for hand-ref formatting; group by the EFFECTIVE
        # opener position (table-size-adjusted) — the real strategic axis.
        for d in wide_bb:
            d['_render_position'] = 'BB'
            if not d.get('opener_effective'):
                d['opener_effective'] = d.get('opener', '—')
        for opener, group in _by_position(wide_bb, key='opener_effective'):
            anchor = f"sec-17-2-vs-{opener.lower().replace('+','plus')}"
            doc.w(f"<<ANCHOR:{anchor}>>")
            doc.w(f"<<ANCHOR_COMPAT:sec-xiii-2-vs-{opener.lower().replace('+','plus')}>>")
            doc.w(f"#### S17.2 — Wide BB Defends vs {opener} open (effective) "
                  f"({len(group)})")
            doc.w("")
            # v7.38 (Ron's request): clearer headers — Hero pos is always BB,
            # so just show Opener pos + n_players + effective chart-shift.
            # v7.39: + MDA Note column.
            _bb_hdr = "| Hand (Hero=BB) | Cards | Opener | Tbl | Eff Chart Pos | Severity | Chart | Chart Includes | MDA Note |"
            _bb_sep = "|---|---|---|---|---|---|---|---|---|"
            _bb_rows = []
            for d in group:
                d_with_bb = dict(d); d_with_bb['position'] = 'BB'
                href = _href(d_with_bb, s['_hands_by_id'])
                chart = d.get('chart', '—')
                sz = d.get('chart_size', '?')
                bound = d.get('chart_summary', '—') or '—'
                chart_label = f"`{chart}` (n={sz})" if chart != '—' else '—'
                if d.get('chart_augmented'):
                    chart_label = f"⚠️ {chart_label} (chart-augmented +{d.get('chart_augmented_count','?')})"
                npl = d.get('n_players', '?')
                tbl_str = f"{npl}p" if npl != '?' else '?'
                eff_op = d.get('opener_effective', d.get('opener','—'))
                eff_str = eff_op if eff_op != d.get('opener') else '—'
                sev = d.get('severity', d.get('confidence','—'))
                # v8.8.6 S1: satellite/ICM caveat
                _d_fmt_bb = (d.get('format') or '').upper()
                if _d_fmt_bb == 'SATELLITE' and sev == 'CLEAR':
                    sev = 'CLEAR chipEV-only · SAT/ICM caveat'
                if d.get('confidence_downgrade_reason'):
                    sev = f"{sev} ⚠️"
                ovl = d.get('mda_overlay')
                mda_note = (f"`{ovl['rec_id']}` {ovl['ev_bb']:+.1f} BB ({ovl['confidence']})"
                            if ovl else '—')
                _bb_rows.append(f"| {href} | {_real_cards_pills(d, s['_hands_by_id'])} | "
                      f"{d.get('opener','—')} | {tbl_str} | {eff_str} | "
                      f"{sev} | {chart_label} | {bound} | {mda_note} |")
            _bb_blk = raw_reference_block(
                f"xiii2-wide-bb-vs-{opener.lower().replace('+','plus')}",
                _bb_hdr, _bb_sep, _bb_rows)
            doc.write_block(_bb_blk)
            doc.w("")
            _emit_correct_ranges(doc, group, s.get('_dev_charts', {}))
            _bb_anchor = f"sec-17-2-vs-{opener.lower().replace('+','plus')}"
            doc.w(f'<<REVIEWROW|sub|{_bb_anchor}|Wide BB Defends vs {opener}>>')

    # XIII.3 All Missed Opens — grouped by Hero position
    missed = [d for d in devs if d.get('type') == 'Missed Open']
    doc.subsection("sec-17-3", "S17.3 All Missed Opens",
                   f"{len(missed)} flagged missed-open spots (grouped by position)")
    doc.w("↩ [Back to S4.2 Out-of-Bound Leak Discovery](#sec-4-2)")
    doc.w("")
    if not missed:
        doc.w("👍 None flagged.")
        doc.w("")
    else:
        for pos, group in _by_position(missed, key='pos'):
            anchor = f"sec-17-3-{pos.lower().replace('+','plus')}"
            doc.w(f"<<ANCHOR:{anchor}>>")
            doc.w(f"<<ANCHOR_COMPAT:sec-xiii-3-{pos.lower().replace('+','plus')}>>")
            doc.w(f"#### S17.3 — Missed Opens at {pos} ({len(group)})")
            doc.w("")
            _emit_table_compact(
                ['Hand Reference', 'Cards', 'Severity', 'Chart', 'Chart Includes', 'MDA Note'],
                [_row_data(d) for d in group],
                block_id=f"xiii3-missed-opens-{pos.lower().replace('+','plus')}")
            doc.w("")
            _emit_correct_ranges(doc, group, s.get('_dev_charts', {}))
            doc.w(f'<<REVIEWROW|sub|{anchor}|Missed Opens at {pos}>>')

    # XIII.4 All Mistakes — split by confidence (CLEAR vs MARGINAL) AND review status
    # v7.39: Ron flagged the "4 confirmed but 3 are marginal" inconsistency. Previous
    # logic treated `confirmed_list = mistakes - needs_review - auto_corrected` as a
    # single bucket and labeled it "auto-confirmed", which conflated two distinct
    # concepts: (a) the reviewer didn't kick this to manual review, and (b) the
    # detector confidence was high. Now split survivors by `confidence` field so
    # CLEAR mistakes (real leaks) and MARGINAL mistakes (line-review candidates)
    # render as separate subsections. The TL;DR "X confirmed" count = CLEAR only.
    mistakes = s.get('mistakes', [])
    rev = rd.get('reviewed_mistakes', {})
    needs_review_list = rev.get('needs_review', []) or []
    auto_corrected_list = rev.get('auto_corrected', []) or []
    needs_keys = {(m.get('id'), m.get('type')) for m in needs_review_list}
    auto_keys = {(m.get('id'), m.get('type')) for m in auto_corrected_list}
    survivors = [m for m in mistakes
                 if (m.get('id'), m.get('type')) not in needs_keys
                 and (m.get('id'), m.get('type')) not in auto_keys]
    # B173 (Ron 2026-05-24): a hand the analyst explicitly cleared with a
    # III.0/III.3/III.4/III.5 verdict is NOT a confirmed mistake — it was reviewed
    # and overturned. The survivor filter previously subtracted only
    # needs_review + auto_corrected, so an analyst-cleared CLEAR-confidence
    # detector flag (e.g. 91328435, Wide CVJ cleared as III.3) still landed in
    # XIII.4.1 and the headline count, contradicting III.3's own cleared list.
    # Subtract the analyst-override set here, the same set III already nets out
    # of the punt count.
    # Bug fix (Ron 2026-05-30): use canonical _MISTAKE_CLEARED_PREFIXES
    # instead of a local subset — was missing III.8, I.7, 'no leak'.
    from gem_report_draft.sections_mistakes import _MISTAKE_CLEARED_PREFIXES
    _ac_xiii = (rd.get('analyst_commentary') or {})
    _override_ids_xiii = {hid for hid, cmt in _ac_xiii.items()
                          if isinstance(cmt, dict)
                          and cmt.get('verdict', '').startswith(
                              _MISTAKE_CLEARED_PREFIXES)}
    if _override_ids_xiii:
        survivors = [m for m in survivors
                     if m.get('id') not in _override_ids_xiii]
    clear_list = [m for m in survivors if (m.get('confidence', '') or '').upper() == 'CLEAR']
    # v7.43 tail-fold split: MARGINAL Missed Steal/Push are bottom-of-chart
    # mixed-strategy folds — surfaced separately, not counted as mistakes.
    # B160 (Ron 2026-05-24): the MARGINAL/CLEAR tier for missed steal/push
    # lives in the TYPE string ("Missed Push <8BB (MARGINAL)"), NOT in the
    # `confidence` field (which is often 'MED' for these). Read both so a
    # MARGINAL missed-push is recognised as a tail-fold, not left "awaiting".
    def _is_tail_fold_local(m):
        t = (m.get('type', '') or '').lower()
        c = (m.get('confidence', '') or '').upper()
        is_steal_push = ('missed steal' in t or 'missed push' in t)
        tier_marginal = ('(marginal)' in t) or (c == 'MARGINAL')
        return is_steal_push and tier_marginal
    tail_fold_list = [m for m in survivors if _is_tail_fold_local(m)]
    # Missed-PUSH hands route through needs_review (unlike missed-steals,
    # which land in `survivors`); pull any tail-fold back out of needs_review
    # so a MARGINAL missed-push is surfaced info-only in XIII.4.2b instead of
    # being stranded in the XIII.4.4 awaiting list.
    _tf_ids = {m.get('id') for m in tail_fold_list}
    for m in needs_review_list:
        if _is_tail_fold_local(m) and m.get('id') not in _tf_ids:
            tail_fold_list.append(m)
            _tf_ids.add(m.get('id'))
    marginal_list = [m for m in survivors
                     if (m.get('confidence', '') or '').upper() == 'MARGINAL'
                     and not _is_tail_fold_local(m)]
    other_list = [m for m in survivors
                  if (m.get('confidence', '') or '').upper() not in ('CLEAR', 'MARGINAL')]

    # v7.39 (Ron's request 2026-05-09): #/100 alongside absolute counts.
    n_h = len(hands) or 1
    # B187 (Ron 2026-05-25): the header count must distinguish hands genuinely
    # awaiting an analyst verdict from those already reviewed — otherwise a
    # fully-graded run still advertises "N require human review". These
    # bindings (also used by XIII.4.4/4.5 below) are defined once, here.
    synth = (rd.get('analyst_commentary', {}) or {}).get('__synthesis__', {})
    _mr_raw = synth.get('mistakes_review', {}) if isinstance(synth, dict) else {}
    mistakes_review = _mr_raw if isinstance(_mr_raw, dict) else {}
    analyst_all = rd.get('analyst_commentary', {}) or {}
    _nr_await = _nr_judged = 0
    if needs_review_list:
        from collections import defaultdict as _dd
        _byh = _dd(list)
        for _m in needs_review_list:
            _byh[_m.get('id')].append(_m)
        for _hid, _grp in _byh.items():
            _c = mistakes_review.get(_hid) or analyst_all.get(_hid)
            if isinstance(_c, dict) and _c.get('verdict'):
                _nr_judged += 1
            elif _grp and all(_is_tail_fold_local(_m) for _m in _grp):
                continue
            else:
                _nr_await += 1
    summary_parts = [f"{len(clear_list)} CLEAR confirmed ({100.0*len(clear_list)/n_h:.2f}/100)"]
    # B208 (Ron 2026-05-25): count analyst-confirmed mistakes (III.1 punts +
    # III.2 strategic leaks) the detector did NOT independently flag — they
    # belong in the mistake ledger (Ron: "classified as a mistake that didn't
    # enter mistakes/100 nor XIII.4 — this is a bug").
    _clear_ids_b208 = {m.get('id') for m in clear_list}
    _detector_flag_ids = {m.get('id') for m in mistakes}
    _analyst_confirmed = [
        hid for hid, c in (analyst_all.items() if isinstance(analyst_all, dict) else [])
        if isinstance(c, dict) and (c.get('verdict', '') or '').startswith(('III.1', 'III.2'))
        and hid not in _clear_ids_b208 and hid not in _detector_flag_ids]
    if _analyst_confirmed:
        _tot = len(clear_list) + len(_analyst_confirmed)
        summary_parts.append(
            f"{len(_analyst_confirmed)} analyst-confirmed III.1/III.2 "
            f"— total {_tot} mistakes ({100.0*_tot/n_h:.2f}/100)")
    if marginal_list:
        summary_parts.append(f"{len(marginal_list)} MARGINAL ({100.0*len(marginal_list)/n_h:.2f}/100)")
    if tail_fold_list:
        summary_parts.append(f"{len(tail_fold_list)} TAIL FOLDS info-only ({100.0*len(tail_fold_list)/n_h:.2f}/100)")
    if other_list:
        summary_parts.append(f"{len(other_list)} other")
    if needs_review_list:
        if _nr_await:
            summary_parts.append(f"{_nr_await} require human review")
        if _nr_judged:
            summary_parts.append(f"{_nr_judged} analyst-reviewed")
    if auto_corrected_list:
        summary_parts.append(f"{len(auto_corrected_list)} auto-corrected")
    doc.subsection("sec-17-4", "S17.4 All Mistakes",
                   f"{len(mistakes)} raw = {100.0*len(mistakes)/n_h:.2f}/100 — " + ", ".join(summary_parts))
    # B170 (Ron 2026-05-24): per-subsection XIV.B links emitted below each
    # sub-table instead of one ambiguous top-level "All Mistakes" link.
    doc.w("")

    # Issue 2 (v7.71, Ron 2026-05-23): opening-range reference for Missed
    # Steal flags. A Missed-Steal flag used to tell Ron a hand was a fold it
    # should not have been — without ever telling him the range it should
    # have opened from. The detector uses the curated CORE/EXTENDED tier
    # sets, which ARE the authority / fallback when an OCR chart for this
    # exact position+depth is missing (B17). Surface those ranges once per
    # position so every Missed-Steal row below is self-contained.
    _ms_mistakes = [m for m in mistakes
                    if 'Missed Steal' in (m.get('type', '') or '')
                    and m.get('open_range_core')]
    if _ms_mistakes:
        _ms_by_pos = {}
        for m in _ms_mistakes:
            _ms_by_pos.setdefault(m.get('pos', '?'), m)
        doc.w("**Correct opening ranges** — *for the Missed-Steal flags below. "
              "Source: the curated position-tier opening framework, which is "
              "the authority when an OCR chart for the exact depth is missing "
              "(B17). CORE folds = CLEAR missed steals; EXTENDED folds = "
              "MARGINAL (table/stack dependent).*")
        doc.w("")
        for _pos in [p for p in ('CO', 'BTN', 'SB') if p in _ms_by_pos]:
            _m = _ms_by_pos[_pos]
            doc.w(f"- **{_pos} open — CORE:** {_m['open_range_core']}")
            if _m.get('open_range_extended'):
                doc.w(f"- **{_pos} open — EXTENDED (marginal):** "
                      f"{_m['open_range_extended']}")
        doc.w("")
        doc.w("*Each Missed-Steal row's Detail column shows which tier the "
              "folded hand sits in.*")
        doc.w("")

    # B150 (Ron 2026-05-23): correct iso-jam range for Wide Iso-Jam flags —
    # same self-contained treatment as Missed Steal. A "Wide Iso-Jam" flag
    # said the re-jam was too loose without showing what range IS correct.
    _ij_mistakes = [m for m in mistakes
                    if m.get('type') == 'Wide Iso-Jam' and m.get('iso_range')]
    if _ij_mistakes:
        doc.w("**Correct iso-jam ranges** — *for the Wide Iso-Jam flags below. "
              "This is the context-adjusted re-jam range (PKO bounty / Ace "
              "blocker / short-jammer modifiers already applied); a hand "
              "outside it is the flagged over-loose re-jam.*")
        doc.w("")
        for _m in _ij_mistakes:
            _jb = _m.get('jammer_bb')
            _jp = _m.get('jammer')
            _ctx = (f" (vs {_jp} {_jb}BB jam)"
                    if _jp and _jb is not None else '')
            _rng = _m.get('iso_range') or []
            doc.w(f"- **{_real_cards_pills(_m, s['_hands_by_id'])} re-jam{_ctx}** — correct range "
                  f"({len(_rng)} combos): {_compact_range(_rng)}")
        doc.w("")

    # Mistake-review commentary (LLM judgments per needs_review hand).
    # synth / mistakes_review / analyst_all are bound once near the header
    # count above (B187) — reused here.

    _MISTAKE_TABLE_CAP = 20  # show first N, rest in expandable <details>

    def _emit_mistake_table(rows, block_id=None):
        if not rows:
            doc.w("👍 None.")
            doc.w("")
            return
        _mt_hdr = "| Hand Reference | Cards | Type | EV | Detail |"
        _mt_sep = "|---|---|---|---|---|"

        def _build_rows(row_list):
            out = []
            for m in row_list:
                href = _href(m, s['_hands_by_id'])
                ev = m.get('estimated_ev_bb', m.get('corrected_ev', m.get('ev', '—')))
                ev_str = f"{ev:+.1f} BB" if isinstance(ev, (int, float)) else str(ev)
                if m.get('range_tier'):
                    detail = (f"{m.get('cards','?')} sits in {m['range_tier']} of "
                              f"the {m.get('pos','?')} open range")
                    if m.get('range_tier') == 'CORE' and m.get('tier_demoted'):
                        detail += f" (demoted → marginal: {m.get('demotion_reason','context')})"
                else:
                    detail = (m.get('action_summary') or m.get('detail') or '—')[:80]
                out.append(f"| {href} | {_real_cards_pills(m, s['_hands_by_id'])} | {m.get('type','—')} | "
                      f"{ev_str} | {detail} |")
            return out

        if len(rows) <= _MISTAKE_TABLE_CAP:
            _mt_rows = _build_rows(rows)
            _mt_blk = raw_reference_block(block_id or "xiii4-mistakes", _mt_hdr, _mt_sep, _mt_rows)
            doc.write_block(_mt_blk)
        else:
            # Show first N rows, rest in expandable details
            _mt_rows = _build_rows(rows[:_MISTAKE_TABLE_CAP])
            _mt_blk = raw_reference_block(block_id or "xiii4-mistakes", _mt_hdr, _mt_sep, _mt_rows)
            doc.write_block(_mt_blk)
            _rest = rows[_MISTAKE_TABLE_CAP:]
            doc.w(f"<details><summary><strong>Show {len(_rest)} more "
                  f"({len(rows)} total)</strong></summary>")
            doc.w("")
            _mt_rest = _build_rows(_rest)
            doc.w(_mt_hdr)
            doc.w(_mt_sep)
            for r in _mt_rest:
                doc.w(r)
            doc.w("")
            doc.w("</details>")
        doc.w("")

    # XIII.4.1 — CLEAR Confirmed (the headline "X confirmed" comes from this list)
    doc.w("<<ANCHOR:sec-17-4-confirmed>>")
    doc.w("<<ANCHOR_COMPAT:sec-xiii-4-confirmed>>")
    doc.w(f"#### S17.4.1 🔴 CLEAR Confirmed ({len(clear_list)})")
    doc.w("")
    doc.w("*Detector emitted CLEAR confidence and the type-specific reviewer "
          "didn't override. These are the hands the TL;DR \"X confirmed\" count "
          "comes from. Drill candidates: yes.*")
    doc.w("")
    # B170 (Ron 2026-05-24): route this sub-table's hand citations to the
    # sub-anchor so XIV.B labels the group precisely (Confirmed / Tail Folds)
    # when the hand groups under XIII.4 — the keystone fix for "is this a
    # mistake or not". No section-level XIV.B link here: confirmed-mistake
    # hands group under their first-cited section (often an earlier III.* /
    # V.* section), so a hardcoded link would be unreliable — the per-hand
    # references in the table above already jump to each hand's grid.
    _state._set_current_section('sec-17-4-confirmed', 'S17.4.1 Confirmed Mistakes')
    _emit_mistake_table(clear_list, block_id="xiii4-1-clear-confirmed")

    # XIII.4.2 — MARGINAL (borderline / mixed-strategy / GTO override candidates)
    doc.w("<<ANCHOR:sec-17-4-marginal>>")
    doc.w("<<ANCHOR_COMPAT:sec-xiii-4-marginal>>")
    doc.w(f"#### S17.4.2 🟡 MARGINAL ({len(marginal_list)})")
    doc.w("")
    doc.w("*Detector flagged but emitted MARGINAL confidence (bottom-of-range "
          "hand, GTO mixed strategy, or short-sample chart). Treat as line-review "
          "candidates, not as confirmed leaks. NOT counted in the TL;DR \"X confirmed\" "
          "headline.*")
    doc.w("")
    _state._set_current_section('sec-17-4-marginal', 'S17.4.2 Marginal')
    _emit_mistake_table(marginal_list, block_id="xiii4-2-marginal")

    # XIII.4.2b — Tail Folds (info-only): MARGINAL Missed Steal/Push hands.
    # v7.43 (Ron 2026-05-09): bottom-of-chart mixed-strategy folds aren't
    # mistakes — they're chart-tail decisions where opening would also be
    # defensible. Surfaced for audit visibility but NOT counted in the
    # mistake metric (headline + TL;DR per-100). EV cost contribution is
    # nominal noise (~0.5-1 BB per spot at the tail).
    if tail_fold_list:
        doc.w("<<ANCHOR:sec-17-4-tail>>")
        doc.w("<<ANCHOR_COMPAT:sec-xiii-4-tail>>")
        doc.w(f"#### S17.4.2b ⚪ Tail Folds — info-only ({len(tail_fold_list)})")
        doc.w("")
        doc.w("*MARGINAL Missed Steal/Push hands — bottom of opening range where "
              "GTO is mixed-strategy (e.g., a chart 'opens 40%' from this position "
              "means folding the bottom 60% is correct; folding the bottom of the "
              "open range is a mixed-frequency decision, not an error). NOT counted "
              "as a mistake. Surfaced so Ron can review specific spots if a pattern "
              "emerges, but the metric impact is nominal (~0.5 BB/spot). True "
              "frequency-aware classification needs solver-derived per-hand frequencies "
              "from the ranges file.*")
        doc.w("")
        _state._set_current_section('sec-17-4-tail',
                                    'S17.4.2b Tail Folds (info-only)')
        _emit_mistake_table(tail_fold_list, block_id="xiii4-2b-tail-folds")
        # B-V10 (2026-06-01): the back-link must point to an anchor that
        # always exists. The xivb-from-sec-17-4-tail group only renders if
        # hands were cited into XIV.B under that key — which doesn't happen
        # for info-only tail folds. Use the parent mistakes section instead.
        doc.w("🔎 *Tail folds are info-only — full hand grids available in "
              "[XIV.B Quick Lookups](#sec-xivb-quick-lookups)*")
        doc.w("")
    # B170: restore section context for any downstream XIII.4 content.
    _state._set_current_section('sec-17-4', 'S17.4 All Mistakes')

    # XIII.4.3 — Other (unlabeled confidence — defensive bucket for legacy detectors)
    if other_list:
        doc.w(f"#### S17.4.3 Other detector output ({len(other_list)})")
        doc.w("")
        doc.w("*Detector emitted neither CLEAR nor MARGINAL — treat as borderline "
              "until the detector is updated to label confidence explicitly.*")
        doc.w("")
        _emit_mistake_table(other_list, block_id="xiii4-3-other")

    # XIII.4.4 — Requires Human Review (with LLM judgment if present)
    # Renamed from "Needs Manual Review" v7.43 (Ron 2026-05-09): "human review"
    # is the cue for the LLM analyst to actually provide judgment, not punt.
    # v7.43+ Ron: split judged hands (verdict present) out of "awaiting review"
    # into "Analyst-Reviewed" so awaiting list isn't polluted.
    judged_hands = []
    awaiting_hands = []
    if needs_review_list:
        from collections import defaultdict
        by_hand = defaultdict(list)
        for m in needs_review_list:
            by_hand[m.get('id')].append(m)
        for hid, group in by_hand.items():
            # B187: a verdict in the main analyst pass (session_analysis) clears
            # the hand the same as one in __synthesis__.mistakes_review. Before
            # this, analyst verdicts on these hands silently failed to move them
            # out of "Awaiting" — the "you left pending hands" bug.
            cmt = mistakes_review.get(hid) or analyst_all.get(hid)
            # v8.7.1 FIX (handover G): type-guard — cmt can be a string if
            # analyst wrote prose instead of a dict. Treat non-dict as pending.
            if isinstance(cmt, str):
                cmt = {'verdict': '', 'argument': cmt}
            if cmt and isinstance(cmt, dict) and cmt.get('verdict'):
                judged_hands.append((hid, group, cmt))
            else:
                # B160 (Ron 2026-05-24): a MARGINAL Missed Steal/Push is a
                # tail-fold — it already shows in XIII.4.2b info-only and is
                # NOT a reviewable mistake (folding the bottom of a mixed
                # open range is a frequency decision, not an error). Exclude
                # it from the awaiting list, mirroring the same exclusion
                # confirmed_list already applies, so a complete analyst pass
                # doesn't surface a phantom "Awaiting (1)".
                if group and all(_is_tail_fold_local(m) for m in group):
                    continue
                awaiting_hands.append((hid, group))

    doc.w("<<ANCHOR:sec-17-4-review>>")
    doc.w("<<ANCHOR_COMPAT:sec-xiii-4-review>>")
    doc.w(f"#### S17.4.4 Flagged for Review ({len(awaiting_hands)})")
    doc.w("")
    doc.w("*Detector-flagged hands that require per-hand judgment. "
          "Verdicts will be assigned during the analyst pass.*")
    doc.w("")
    if awaiting_hands:
        _aw_hdr = "| Hand Reference | Cards | Rule(s) Triggered | Estimated EV |"
        _aw_sep = "|---|---|---|---|"
        _aw_rows = []
        for hid, group in awaiting_hands:
            ref_m = group[0]
            href = _href(ref_m, s['_hands_by_id'])
            cards = _real_cards_pills(ref_m, s['_hands_by_id'])
            rules = "; ".join(m.get('type', '—') for m in group)
            ev = sum((m.get('corrected_ev') or 0) for m in group)
            ev_str = f"{ev:+.1f} BB" if ev else "—"
            _aw_rows.append(f"| {href} | {cards} | {rules} | {ev_str} |")
        _aw_blk = raw_reference_block("xiii4-4-awaiting", _aw_hdr, _aw_sep, _aw_rows)
        doc.write_block(_aw_blk)
        doc.w("")
    else:
        doc.w("👍 None — every flagged hand has an analyst verdict (see XIII.4.5 below).")
        doc.w("")

    # XIII.4.5 — Analyst-Reviewed.
    # B208 (Ron review 2026-05-25): a hand the analyst graded III.1 (punt) or
    # III.2 (strategic leak) that the DETECTOR never independently flagged was
    # orphaned — it showed in the I.3 / XIII.6 large-loss audit with its
    # verdict but never reached XIII.4 or mistakes/100 ("classified as a
    # mistake that didn't enter the table — this is a bug"). Pull every such
    # analyst-only III.1/III.2 hand in here so XIII.4 is the complete mistake
    # ledger. judged_hands already covers detector-flagged + analyst-reviewed;
    # this adds the analyst-only set.
    _judged_ids = {hid for hid, _, _ in judged_hands}
    _analyst_only = []
    for hid, cmt in (analyst_all.items() if isinstance(analyst_all, dict) else []):
        if not isinstance(cmt, dict):
            continue
        v = (cmt.get('verdict', '') or '')
        if v.startswith(('III.1', 'III.2')) and hid not in _judged_ids:
            _analyst_only.append((hid, cmt))
    # RUN-2 fix: always emit anchor so XIV.A backlinks don't break
    doc.w("<<ANCHOR:sec-17-4-reviewed>>")
    if judged_hands or _analyst_only:
        doc.w("<<ANCHOR_COMPAT:sec-xiii-4-reviewed>>")
        doc.w(f"#### S17.4.5 Analyst-Reviewed Mistakes "
              f"({len(judged_hands) + len(_analyst_only)})")
        doc.w("")
        doc.w("*Detector-flagged hands the analyst judged, plus hands the "
              "analyst graded a mistake (III.1 punt / III.2 strategic leak) "
              "that the detector did not independently flag. 🔴/III.1/III.2 "
              "verdicts ARE counted in the mistake ledger; 🟢/🟡 are not. "
              "Click the appendix link for full hand detail.*")
        doc.w("")
        _rv_hdr = "| Hand Reference | Cards | Rule(s) / Source | Verdict | Full Detail |"
        _rv_sep = "|---|---|---|---|---|"
        _rv_rows = []
        for hid, group, cmt in judged_hands:
            ref_m = group[0]
            href = _href(ref_m, s['_hands_by_id'])
            cards = _real_cards_pills(ref_m, s['_hands_by_id'])
            rules = "; ".join(m.get('type', '—') for m in group)
            verdict = cmt.get('verdict', '—')
            appendix_anchor = f"sec-app-hand-{hid[-8:]}"
            _rv_rows.append(f"| {href} | {cards} | {rules} | {verdict} | "
                  f"{_xref(appendix_anchor, label='full HH ↓')} |")
        for hid, cmt in _analyst_only:
            h = (s.get('_hands_by_id', {}) or {}).get(hid, {})
            href = _href(h, s['_hands_by_id']) if h else f"`{hid[-8:]}`"
            cards = (_cards_str_to_pills(''.join(h.get('cards', []) or []))
                     if h else '—')
            verdict = cmt.get('verdict', '—')
            appendix_anchor = f"sec-app-hand-{hid[-8:]}"
            _rv_rows.append(f"| {href} | {cards} | analyst pass (no detector flag) | "
                  f"{verdict} | {_xref(appendix_anchor, label='full HH ↓')} |")
        _rv_blk = raw_reference_block("xiii4-5-analyst-reviewed", _rv_hdr, _rv_sep, _rv_rows)
        doc.write_block(_rv_blk)
        doc.w("")
        doc.w("**Analyst arguments:**")
        doc.w("")
        for hid, group, cmt in judged_hands:
            argument = cmt.get('argument', '')
            if argument:
                doc.w(f"- **`{hid[-8:]}`** ({cmt.get('verdict','')}): {argument}")
        for hid, cmt in _analyst_only:
            argument = cmt.get('argument', '')
            if argument:
                doc.w(f"- **`{hid[-8:]}`** ({cmt.get('verdict','')}): {argument}")
        doc.w("")
    doc.w("")

    # XIII.4.6 — Auto-corrected (rare — when reviewer downgraded the EV impact)
    if auto_corrected_list:
        doc.w("<<ANCHOR:sec-17-4-autocorr>>")
        doc.w("<<ANCHOR_COMPAT:sec-xiii-4-autocorr>>")
        doc.w(f"#### S17.4.6 Auto-Corrected ({len(auto_corrected_list)})")
        doc.w("")
        doc.w("*Detector flag was overridden by post-review correction (EV recomputed).*")
        doc.w("")
        _ac_hdr = "| Hand Reference | Cards | Type | Corrected EV | Reason |"
        _ac_sep = "|---|---|---|---|---|"
        _ac_rows = []
        for m in auto_corrected_list:
            href = _href(m, s['_hands_by_id'])
            ev = m.get('corrected_ev', '—')
            ev_str = f"{ev:+.1f} BB" if isinstance(ev, (int, float)) else str(ev)
            _ac_rows.append(f"| {href} | {_real_cards_pills(m, s['_hands_by_id'])} | {m.get('type','—')} | "
                  f"{ev_str} | {m.get('reason','—')[:60]} |")
        _ac_blk = raw_reference_block("xiii4-6-auto-corrected", _ac_hdr, _ac_sep, _ac_rows)
        doc.write_block(_ac_blk)
        doc.w("")

    # ============================================================
    # XIII.5 — MDA Population Exploits (v7.39 spot-based + v7.41 v9 frequency)
    # ============================================================
    # Two-tier surface:
    #   (a) Per-hand aligned/missed exploits from gem_mda_overlay.find_aligned_and_missed
    #   (b) Session-frequency tests (v9 Recs 20-25) — Hero's session rates vs
    #       MDA-recommended bands. The architectural unlock for "no value
    #       per-hand" critique: per-hand alignment over default-correct plays
    #       is noise; session-frequency tests against population baselines is
    #       signal.
    mda = s.get('mda_exploits', {}) or {}
    aligned_all = mda.get('aligned', []) or []
    missed_mda = mda.get('missed', []) or []
    freq_signals = s.get('mda_frequency_signals', []) or []

    # v7.41: suppress trivial alignments — when Hero made the default play
    # (e.g., 3-bet KK BB vs MP open), surfacing it as an "aligned exploit"
    # overstates the framework. Define trivial = combos every reg plays the
    # same way, by rec.
    TRIVIAL_BY_REC = {
        'MDA-2a': set(),  # combo set already restricted to exploit-edge in v7.40
        # MDA-4 / MDA-16: any alignment counts (premium pair commit at short stack
        # IS the genuine exploit per the framework — stacks are short enough that
        # population folding TT+ is the actual leak).
    }
    aligned = []
    suppressed_count = 0
    for entry in aligned_all:
        rec_id = entry.get('mda_rec_id')
        combo = entry.get('cards')
        if rec_id in TRIVIAL_BY_REC and combo in TRIVIAL_BY_REC[rec_id]:
            suppressed_count += 1
            continue
        aligned.append(entry)

    # Headline counts include freq-test signals
    n_freq_flag = sum(1 for f in freq_signals if f.get('verdict') == 'FLAG')
    n_freq_aligned = sum(1 for f in freq_signals if f.get('verdict') == 'ALIGNED')

    summary_bits = [f"{len(aligned)} aligned spots", f"{len(missed_mda)} missed spots"]
    if freq_signals:
        summary_bits.append(f"{n_freq_aligned} freq-aligned, {n_freq_flag} freq-flag")
    doc.subsection("sec-17-5", "S17.5 MDA Population Exploits",
                   " | ".join(summary_bits)
                   + " — online-pool-specific (sits parallel to Jaka)")
    doc.w("*MDA recommendations are POPULATION exploits derived from a 14,327-file "
          "MTT dataset (~2.1M hands; v9 spec). They sit at the same priority slot "
          "as Jaka K-rules — below Dave J-series, above default GTO. Source: "
          "[`MTT_Tactical_Recommendations_v9_FINAL.md`](MTT_Tactical_Recommendations_v9_FINAL.md).*")
    doc.w("")
    if mda.get('error'):
        doc.w(f"⚠️ MDA overlay computation failed: {mda['error']}")
        doc.w("")

    # ---- XIII.5.0: Frequency-test summary (NEW — v9 architectural unlock) ----
    if freq_signals:
        # v7.42: cross-session aggregation. When session_history is available,
        # accumulate prior sessions' Flop_CBet_MW / Flop_CBet_HU rates so the
        # frequency-tests that go THIN this session can still get a verdict
        # from cumulative data. Weights by hand count per session as a
        # pragmatic approximation; precise weighting would need raw count
        # cols which session_history doesn't expose.
        trend_rows = rd.get('trend_data', []) or []
        cumulative = {}  # metric → (weighted_sum, total_weight, n_sessions)
        for row in trend_rows:
            try:
                hands_v = float(row.get('Hands') or 0)
            except (TypeError, ValueError):
                hands_v = 0
            if hands_v <= 0: continue
            for csv_col, metric in (('Flop_CBet_MW', 'mw_cbet_pct'),
                                     ('Flop_CBet_HU', 'connected_low_cbet_pct'),
                                     # v7.66: K-series frequency overlays — these
                                     # CSV columns exist in session_history, so
                                     # K2/K3/K6 get a cross-session estimate too.
                                     ('Flop_CBet_HU_OOP', 'k2_oop_pfr_cbet_pct'),
                                     ('IP_Stab_Rate', 'k3_ip_stab_rate'),
                                     ('Flop_Lead_Rate', 'k6_flop_lead_rate')):
                try:
                    v = float(row.get(csv_col) or 0)
                except (TypeError, ValueError):
                    continue
                if v <= 0: continue  # skip 0-rows (likely missing data)
                ws, w, n = cumulative.get(metric, (0.0, 0.0, 0))
                # Weight by hand count as a pragmatic stand-in for opp count
                cumulative[metric] = (ws + v * hands_v, w + hands_v, n + 1)

        doc.w(f"##### XIII.5.0 Session Frequency Tests ({len(freq_signals)})")
        doc.w("")
        doc.w("*Hero's session-aggregate rates vs MDA-recommended bands. "
              "Tests population-exploit alignment at the **frequency** level "
              "rather than per-hand. ALIGNED = in target band; FLAG = needs "
              "adjustment (direction shown); THIN = sample too small for verdict "
              "this session. **Cumulative** column shows cross-session rolling "
              "estimate when prior data exists (weighted by session hand count).*")
        doc.w("")
        _fq_hdr = "| Rec | Description | Hero (this session) | n | Cumulative | Sessions | Target | Pop avg | Verdict | Note |"
        _fq_sep = "|---|---|---|---|---|---|---|---|---|---|"
        _fq_rows = []
        for f in freq_signals:
            verdict_icon = {'ALIGNED': '✅', 'FLAG': '🔴', 'THIN': '⚪'}.get(
                f.get('verdict'), '?')
            hero_lbl = (f"{f['hero_pct']:.1f}%" if f.get('hero_pct') is not None
                        else '—')
            target_lbl = f"{f['target_lo']}-{f['target_hi']}%"
            metric = f.get('metric', '')
            cum = cumulative.get(metric)
            if cum and cum[1] > 0:
                cum_pct = cum[0] / cum[1]
                cum_lbl = f"{cum_pct:.1f}% (~{int(cum[1])} hands)"
                cum_n = str(cum[2])
                # If THIN this session but cumulative is in band, escalate verdict
                if f.get('verdict') == 'THIN':
                    if f['target_lo'] <= cum_pct <= f['target_hi']:
                        verdict_icon = '✅'
                        f = {**f, 'verdict': 'ALIGNED-cum',
                             'note': f"THIN this session; cumulative {cum_pct:.1f}% IN target across {cum[2]} sessions"}
                    elif cum_pct < f['target_lo']:
                        verdict_icon = '🔴'
                        f = {**f, 'verdict': 'FLAG-cum',
                             'note': f"THIN this session; cumulative {cum_pct:.1f}% too tight — {f['direction']} per MDA"}
                    elif cum_pct > f['target_hi']:
                        verdict_icon = '🔴'
                        f = {**f, 'verdict': 'FLAG-cum',
                             'note': f"THIN this session; cumulative {cum_pct:.1f}% too loose — {f['direction']} per MDA"}
            else:
                cum_lbl = '—'
                cum_n = '—'
            _fq_rows.append(f"| `{f['id']}` | {f['description']} | {hero_lbl} | "
                  f"{f.get('n', 0)} | {cum_lbl} | {cum_n} | {target_lbl} | {f.get('pop_avg', '—')} | "
                  f"{verdict_icon} {f.get('verdict')} | {f.get('note', '')} |")
        _fq_blk = raw_reference_block("xiii5-0-freq-tests", _fq_hdr, _fq_sep, _fq_rows)
        doc.write_block(_fq_blk)
        doc.w("")

    if aligned:
        doc.w(f"##### XIII.5.1 Aligned With MDA — Spot-Level ({len(aligned)})")
        doc.w("")
        doc.w("*Hero's action matched the MDA recommendation in these spots — keep doing this.*")
        doc.w("")
        _al_hdr = "| Hand Reference | Cards | Position | Stack | Rec | Hero | MDA Action | EV/event |"
        _al_sep = "|---|---|---|---|---|---|---|---|"
        _al_rows = []
        # Cap at 25 to avoid overwhelming long sessions
        for entry in aligned[:25]:
            hand_stub = {'id': entry.get('hand_id'),
                         'position': entry.get('position'),
                         'stack_bb': entry.get('stack_bb')}
            href = _href(hand_stub, s['_hands_by_id'])
            ev = entry.get('ev_bb', 0) or 0
            sb = entry.get('stack_bb')
            sb_label = f"{sb:.1f}BB" if isinstance(sb, (int, float)) else f"{sb}BB"
            # v7.41: counter-rec EV semantics — when Hero aligns with a
            # TIGHTEN recommendation, the rec's ev_bb is the COST of NOT
            # tightening (negative). Hero followed the rec, so the alignment
            # is an avoided-cost positive — flip sign and label clearly.
            ev_range = entry.get('ev_bb_range')
            is_counter = entry.get('counter_rec', False)
            pending = entry.get('pending_field')
            if is_counter:
                # Hero aligned with the TIGHTEN — they avoided the negative-EV cost
                ev_label = f"avoided {ev:+.1f} BB"
                if pending:
                    ev_label += f" ⚠️ {pending}"
            elif ev_range and isinstance(ev_range, (list, tuple)) and len(ev_range) == 2:
                ev_label = f"+{ev_range[0]:.0f} to +{ev_range[1]:.0f} BB"
            else:
                ev_label = f"{ev:+.1f} BB"
            _al_rows.append(f"| {href} | {_real_cards_pills(entry, s['_hands_by_id'])} | "
                  f"{entry.get('position','—')} | {sb_label} | "
                  f"`{entry.get('mda_rec_id','—')}` | {entry.get('hero_action','—')} | "
                  f"{entry.get('mda_action','—')} | {ev_label} |")
        if len(aligned) > 25:
            _al_rows.append(f"| … | _{len(aligned)-25} more not shown_ | | | | | | |")
        _al_blk = raw_reference_block("xiii5-1-aligned-mda", _al_hdr, _al_sep, _al_rows)
        doc.write_block(_al_blk)
        doc.w("")
    if missed_mda:
        doc.w(f"##### XIII.5.2 Missed MDA Exploits — Spot-Level ({len(missed_mda)})")
        doc.w("")
        doc.w("*Hero's action DEVIATED from the MDA recommendation. These are EV "
              "leaks specifically in the online MTT pool — drill candidates if "
              "the pattern recurs across sessions.*")
        doc.w("")
        _ms_hdr = "| Hand Reference | Cards | Position | Stack | Rec | Hero Did | MDA Says | EV/event |"
        _ms_sep = "|---|---|---|---|---|---|---|---|"
        _ms_rows = []
        for entry in missed_mda[:25]:
            hand_stub = {'id': entry.get('hand_id'),
                         'position': entry.get('position'),
                         'stack_bb': entry.get('stack_bb')}
            href = _href(hand_stub, s['_hands_by_id'])
            ev = entry.get('ev_bb', 0) or 0
            sb = entry.get('stack_bb')
            sb_label = f"{sb:.1f}BB" if isinstance(sb, (int, float)) else f"{sb}BB"
            ev_range = entry.get('ev_bb_range')
            if ev_range and isinstance(ev_range, (list, tuple)) and len(ev_range) == 2:
                ev_label = f"+{ev_range[0]:.0f} to +{ev_range[1]:.0f} BB"
            else:
                ev_label = f"{ev:+.1f} BB"
            _ms_rows.append(f"| {href} | {_real_cards_pills(entry, s['_hands_by_id'])} | "
                  f"{entry.get('position','—')} | {sb_label} | "
                  f"`{entry.get('mda_rec_id','—')}` | {entry.get('hero_action','—')} | "
                  f"{entry.get('mda_action','—')} | {ev_label} |")
        if len(missed_mda) > 25:
            _ms_rows.append(f"| … | _{len(missed_mda)-25} more not shown_ | | | | | | |")
        _ms_blk = raw_reference_block("xiii5-2-missed-mda", _ms_hdr, _ms_sep, _ms_rows)
        doc.write_block(_ms_blk)
        doc.w("")
    if not aligned and not missed_mda:
        doc.w("*No MDA-tagged spots in this session's hands. As MDA recommendations "
              "expand, this section grows.*")
        doc.w("")

    # ============ XIII.6: Full Large-Loss Audit ============
    # B113 (Ron 2026-05-19): the I.3 section caps at 12 rows and says "see
    # XIII for full list" — but until now that link didn't exist. This is
    # the full table with all bust hands (>25BB lost) in the same column
    # format as I.3, plus a back-link to I.3.
    busts_all = sorted([h for h in hands if h.get('net_bb', 0) < -25],
                       key=lambda h: h['net_bb'])
    if busts_all:
        analyst = rd.get('analyst_commentary', {}) or {}
        cooler_ids_full = set((c.get('id') or '') for c in
                              (rd.get('coolers') or s.get('coolers', {}).get('hands', []) or []))
        i7_ids_full = {hid for hid, cmt in analyst.items()
                       if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('I.7')}
        cooler_ids_full = cooler_ids_full | i7_ids_full
        iii0_ids_full = {hid for hid, cmt in analyst.items()
                         if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.0')}
        iii1_ids_full = {hid for hid, cmt in analyst.items()
                         if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.1')}
        iii2_ids_full = {hid for hid, cmt in analyst.items()
                         if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.2')}
        iii3_ids_full = {hid for hid, cmt in analyst.items()
                         if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.3')}
        iii4_ids_full = {hid for hid, cmt in analyst.items()
                         if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.4')}
        iii5_ids_full = {hid for hid, cmt in analyst.items()
                         if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.5')}
        doc.subsection("sec-17-6", "S17.6 Full Large-Loss Audit",
                       f"all {len(busts_all)} hands lost >25BB "
                       f"({_xref('sec-1-3', label='back to S1.3 ↑')})")
        # B217 (Ron review 2026-05-25): same change as I.3 — "Key Decision"
        # (always empty) → "Type" after Verdict, rows ordered by category
        # (punts → mistakes → read-dep → coolers → suckouts → others).
        _ll_hdr = "| Hand Reference | Cards | Net | Board | Verdict | Type |"
        _ll_sep = "|---|---|---|---|---|---|"

        def _bust_cat_full(hid):
            cmt_l = analyst.get(hid, {}) or {}
            oc = (cmt_l.get('outcome') or '').strip().lower()
            if hid in iii1_ids_full:
                return 1, cmt_l.get('label') or 'Punt'
            if hid in iii2_ids_full:
                return 2, cmt_l.get('label') or 'Strategic leak'
            if hid in iii4_ids_full:
                return 3, cmt_l.get('label') or 'Read-dependent'
            if hid in cooler_ids_full:
                return 4, cmt_l.get('label') or 'Cooler'
            if hid in iii3_ids_full and oc == 'suckout':
                return 5, cmt_l.get('label') or 'Suckout'
            if hid in iii0_ids_full:
                return 6, cmt_l.get('label') or 'GTO-Standard'
            if hid in iii3_ids_full:
                return 6, cmt_l.get('label') or 'Cleared'
            if hid in iii5_ids_full:
                return 6, cmt_l.get('label') or 'Justified'
            return 6, cmt_l.get('label') or '—'

        _ll_rows = []
        for h in sorted(busts_all,
                        key=lambda h: (_bust_cat_full(h.get('id', ''))[0],
                                       -abs(h.get('net_bb', 0)))):
            hid = h.get('id', '')
            if hid in iii1_ids_full:
                verdict = f"👎 punt — {_xref('sec-2-1', label='S2.1')}"
            elif hid in iii2_ids_full:
                verdict = f"👎 mistake — {_xref('sec-17-4', label='S17.4')}"
            elif hid in iii0_ids_full:
                _oce, _oct = _outcome_label(analyst.get(hid, {}),
                                            default=('⚖️', 'GTO-Standard'))
                verdict = f"{_oce} {_oct} — {_xref('sec-13-1', label='S13.1')}"
            elif hid in iii3_ids_full:
                _oce, _oct = _outcome_label(analyst.get(hid, {}))
                verdict = f"{_oce} {_oct} — {_xref('sec-13-1', label='S13.1')}"
            elif hid in iii4_ids_full:
                verdict = f"📖 read-dep — {_xref('sec-13-2', label='S13.2')}"
            elif hid in iii5_ids_full:
                # B251 (Ron review 2026-05-27): a III.5 justified all-in that
                # was a lost flip / suckout now shows its 🪙/🤢 outcome label
                # (auto-tagged by the equity engine) instead of a flat
                # "👍 justified" — same treatment III.3 already gets.
                _oce, _oct = _outcome_label(analyst.get(hid, {}),
                                            default=('👍', 'justified'))
                verdict = f"{_oce} {_oct} — {_xref('sec-13-3', label='S13.3')}"
            elif hid in cooler_ids_full:
                verdict = f"❄️ cooler — {_xref('sec-1-7', label='S1.7')}"
            elif hid in (rd.get('auto_resolved_ids') or []):
                # Issue 6 + auto-resolve expansion (Ron 2026-05-30)
                _ar_label = (rd.get('auto_resolved_labels') or {}).get(hid)
                verdict = _ar_label or "✅ auto-resolved"
            else:
                # Issue 4: variance-outcome fallback before "awaiting"
                _voc_raw = rd.get('variance_outcomes', {}).get(hid)
                _voc = _voc_raw['outcome'] if isinstance(_voc_raw, dict) else _voc_raw
                _voc_map = {
                    'lost_flip': '🪙 lost flip',
                    'suckout': '🤢 suckout',
                    'top_of_range': '🪤 vs top-of-range',
                    'semi_bluff_cooler': '🎲 variance',
                }
                # BUG-7: suppress "awaiting analyst" in published reports
                verdict = _voc_map.get(_voc, "🎲 unclassified variance")
            cards = _cards_str_to_pills(''.join(h.get('cards', [])))
            netbb = h.get('net_bb', 0)
            board_raw = h.get('board') or []
            if isinstance(board_raw, list) and board_raw:
                board_pills = ' '.join(_card_html(c) for c in board_raw)
                board = f'<span style="white-space:nowrap">{board_pills}</span>'
            else:
                board = str(board_raw) if board_raw else '—'
            type_text = _bust_cat_full(hid)[1]
            _ll_rows.append(f"| {_hand_ref(h)} | {cards} | {netbb:+.1f} | "
                  f"{board} | {verdict} | {type_text} |")
        _ll_blk = raw_reference_block("xiii6-large-loss-audit", _ll_hdr, _ll_sep, _ll_rows)
        doc.write_block(_ll_blk)
        doc.w("")
        doc.w(f"*{_xref('sec-1-3', label='↑ back to S1.3 Large-Loss Audit')}*")
        doc.w("")

    # ============ XIII.7: Blind-Spot Audit ============
    # B178 (Ron 2026-05-25): random sample of hands NO detector flagged.
    # The coded heuristics have blind spots; a small reproducible random
    # sample of un-flagged decision hands, reviewed by the analyst, surfaces
    # leaks the rules miss. A sampled hand found to be a real leak is the
    # trigger to build a new detector (New Learning Intake).
    bsa = s.get('blindspot_audit') or {}
    bsa_sampled = bsa.get('sampled') or []
    if bsa_sampled:
        analyst_bsa = rd.get('analyst_commentary', {}) or {}
        hands_by_id_bsa = {h.get('id'): h for h in hands}
        doc.subsection("sec-17-7", "S17.7 Blind-Spot Audit",
                       f"{len(bsa_sampled)} un-flagged decision hands sampled "
                       f"for analyst review — catches leaks the detectors miss")
        doc.w(f"*Random sample: {len(bsa_sampled)} of {bsa.get('frame_size', 0)} "
              f"un-flagged VPIP hands ({bsa.get('total_hands', 0)} total this "
              f"session; ~1% target, floor 3, cap {bsa.get('cap', 8)}, "
              f"date-seeded for reproducibility). These hands tripped NO "
              f"detector — the audit asks whether that is correct. A hand "
              f"found to be a real leak is a candidate for a new detector.*")
        doc.w("")
        # B-AVIEL FEATURE (2026-06-01): analyst coverage callout.
        # Reads __coverage__ from analyst_commentary (analyst-authored).
        # Auto-derives verdicts_written as cross-check.
        _cov = (rd.get('analyst_commentary') or {}).get('__coverage__')
        # Auto-derive verdicts_written from analyst_commentary entries
        _ac_all = rd.get('analyst_commentary') or {}
        _auto_vw = sum(1 for k, v in _ac_all.items()
                       if not k.startswith('__') and isinstance(v, dict)
                       and v.get('verdict'))
        if isinstance(_cov, dict) and _cov.get('candidates_total'):
            _ct = _cov.get('candidates_total', 0)
            _cna = _cov.get('candidates_needs_analyst', 0)
            _re = _cov.get('rows_examined', 0)
            _vw = _cov.get('verdicts_written', _auto_vw)
            _note = _cov.get('note', '')
            doc.w(f"> \U0001F50E **Analyst coverage:** **{_ct}** candidates surfaced "
                  f"by detectors (**{_cna}** needing analyst review) "
                  f"· **{_re}** examined at row level "
                  f"· **{_vw}** written up with full verdicts.")
            if _note:
                doc.w(f">\n> {_note}")
            doc.w("")
        elif _auto_vw > 0:
            # Graceful degradation: no __coverage__ block, but we can count
            # verdicts from the analyst file.
            doc.w(f"> \U0001F50E **Analyst coverage:** **{_auto_vw}** hands "
                  f"written up with full verdicts.")
            doc.w("")
        _bs_hdr = "| Hand Reference | Cards | Pos | Stack | Pot | Net | Verdict |"
        _bs_sep = "|---|---|---|---|---|---|---|"
        _bs_rows = []
        for sh in bsa_sampled:
            hid = sh.get('id', '')
            h_full = hands_by_id_bsa.get(hid, {})
            ref = _hand_ref(h_full) if h_full else f"`{str(hid)[-8:]}`"
            cards = _cards_str_to_pills(''.join(sh.get('cards', []) or []))
            cmt = analyst_bsa.get(hid, {})
            if isinstance(cmt, dict) and cmt.get('verdict'):
                verdict = f"reviewed — {cmt.get('verdict')}"
            else:
                # B228 (Ron 2026-06-01): BSA hands now have XIV.B review
                # modals — link to the appendix card instead of showing a
                # dead-end "pending review" label.
                _hid_short = str(hid)[-8:]
                verdict = f"🔍 [review ↓](#sec-app-hand-{_hid_short})"
            _bs_rows.append(f"| {ref} | {cards} | {sh.get('pos', '?')} | "
                  f"{sh.get('stack_bb', 0)}BB | {sh.get('pot_type', 'SRP')} | "
                  f"{sh.get('net_bb', 0):+.1f} | {verdict} |")
        _bs_blk = raw_reference_block("xiii7-blindspot-audit", _bs_hdr, _bs_sep, _bs_rows)
        doc.write_block(_bs_blk)
        doc.w("")


# ============================================================
# SUMMARY HELPERS
# ============================================================

