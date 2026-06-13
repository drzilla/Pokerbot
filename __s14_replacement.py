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
    _vl_hdr = "| Street | Status | Category | Actual | Expected | Delta | Won | Count |"
    _vl_sep = "|---|:---:|---|---|---|---|---|---|"
    _vl_all_rows = []

    def _ai_rows(street_label, street_data, expectations):
        rows = []
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
            rows.append(
                f"| {street_label} | {status} | {cat.title()} | "
                f"{actual:.1f}% | {exp_str} | {rel:+.0f}% | "
                f"{d.get('won','—')} | {n} |")
        # Total row from eai_ev_adjusted
        adj_key = street_label.lower()
        d = (eai_adj or {}).get(adj_key, {})
        if d:
            delta = d.get('delta_wins', 0)
            emoji = "\U0001f534" if delta < -1.5 else ("\U0001f7e1" if abs(delta) >= 1 else "\U0001f7e2")
            rows.append(
                f"| **{street_label}** | **{emoji}** | **Total** | "
                f"**{d.get('actual_win_pct',0):.1f}%** | "
                f"~{d.get('expected_win_pct',0):.1f}% | "
                f"**{delta:+.1f} wins** | "
                f"**{d.get('actual_wins',0):.1f}** | "
                f"**{d.get('total_spots',0)}** |")
        return rows

    _vl_all_rows.extend(_ai_rows('Preflop', pf,
        [('ahead', 80, '~80%'), ('flip', 55, '~55%'), ('behind', 20, '~20%')]))
    _vl_all_rows.extend(_ai_rows('Postflop', post,
        [('ahead', 85, '~85%'), ('flip', 50, '~50%'), ('behind', 25, '~25%')]))
    # Grand total row
    _gt = {}
    for _adj_k in ('preflop', 'postflop'):
        _d = (eai_adj or {}).get(_adj_k, {})
        for _f in ('total_spots', 'actual_wins', 'delta_wins'):
            _gt[_f] = _gt.get(_f, 0) + _d.get(_f, 0)
    if _gt.get('total_spots'):
        _gt_pct = 100.0 * _gt['actual_wins'] / _gt['total_spots'] if _gt['total_spots'] else 0
        _gt_emoji = "\U0001f534" if _gt['delta_wins'] < -1.5 else ("\U0001f7e1" if abs(_gt['delta_wins']) >= 1 else "\U0001f7e2")
        _vl_all_rows.append(
            f"| **All** | **{_gt_emoji}** | **Grand Total** | "
            f"**{_gt_pct:.1f}%** | — | "
            f"**{_gt['delta_wins']:+.1f} wins** | "
            f"**{_gt['actual_wins']:.1f}** | "
            f"**{_gt['total_spots']}** |")
    _vl_blk = variance_ledger_block("eai-all", _vl_hdr, _vl_sep, _vl_all_rows)
    doc.write_block(_vl_blk)
    doc.w("")
    # Phase 4.8: removed "Total rows are the EAI EV-adjusted signal..." text
    # Phase 4.8: removed "Approximate BB variance..." text block
    # (both per user review -- redundant with the table data)

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
              f'structural coolers in I.7.">'
              f'**\U0001f922 Suckout ledger** — {len(_sk_against)} against Hero · '
              f'{len(_sk_by)} by Hero</span>')
        doc.w("")
        doc.w("| Direction | Hand | Hero | Villain(s) | Board | Hero eq | Street |")
        doc.w("|---|---|---|---|---|---|---|")
        for direction, rows in [("Sucked out", _sk_against), ("Hero sucked out", _sk_by)]:
            for e in sorted(rows, key=lambda x: -(x.get('hero_equity') or 0)):
                _eid = e.get('id', '')
                _short = _eid[-8:]
                _ref = (f"[`{_short}`](#sec-app-hand-{_short}) • "
                        f"{(e.get('tournament') or '')[:28]} "
                        f"({e.get('date','')})")
                _vil = ' / '.join(_cards_str_to_pills(v)
                                  for v in (e.get('villains_all')
                                            or [e.get('villain', '')]))
                _eq = e.get('hero_equity')
                _eq_s = f"{_eq*100:.0f}%" if _eq is not None else "—"
                doc.w(f"| {direction} | {_ref} | "
                      f"{_cards_str_to_pills(e.get('hero','—'))} "
                      f"| {_vil} | {_cards_str_to_pills(e.get('board','—'))} "
                      f"| {_eq_s} | {e.get('street','—')} |")
        doc.w("")

