"""Mental game and Section III (Mistakes) emitters."""

# Issue 5: centralised verdict-prefix constants for punt overrides.
# A hand exits the punt table if analyst gave it ANY non-III.1 verdict.
# III.2 is NOT cleared — it's a confirmed mistake (exits punt table but
# stays in the mistake count). The CLEARED set nets a hand OUT of the
# confirmed-mistake survivor count.
_PUNT_OVERRIDE_PREFIXES = (
    'III.0', 'III.2', 'III.3', 'III.4', 'III.5', 'III.8', 'I.7', 'no leak',
)
_MISTAKE_CLEARED_PREFIXES = (
    'III.0', 'III.3', 'III.4', 'III.5', 'III.8', 'I.7', 'no leak',
)

from gem_report_draft import _state
from gem_report_draft._helpers import (_wilson_ci, _clr, _clr_min, _clr_naive,
    _pctc, _stat_signal, _verdict_ci, _verdict_pct, _hand_ref, _hand_ref_short,
    _xref, _stat_row, _stat_row_pct, _aim_lookup_from_watchlist, _back_to_kpis,
    _compact_range, _run_emoji, _outcome_label, _CI_Z_DEFAULT, _MIN_N_FOR_SIGNAL,
    _RANK_ORD, _break_at_sentences, _href, _emit_correct_ranges,
    _emit_analyst_judgment, _popup_example_ids, _popup_title_with_count,
    _new_badge)
from gem_report_draft._html import (Doc, _card_html, _cards_html,
    _cards_str_to_pills, _cards_text_to_pills, _real_cards_pills, _md_inline, _html_escape,
    _sort_cards_desc, _describe_made_hand, _SUIT_HTML, _RANK_VALUES, _SUIT_VALUES)
from gem_report_draft._hand_grid import _humanize_verdicts, _verdict_display_label
from gem_report_draft._hand_grid import (_render_hand_grid_table,
    _key_decision_action_class, _pick_key_action_idx, _hero_actions_by_street_from_app,
    _hero_action_verbs_by_street_from_app)
from gem_report_draft._blocks import (leak_bucket_overview_block,
    hand_evidence_table_block, metric_table_block, variance_ledger_block)

import gem_made_hands as mh
import gem_coaching as _coach


def _analyst_punt_street_label(cmt, h):
    """v8.12.12 Obj-A: street-aware Type label for an analyst III.1 punt that
    has no `spot` text. Reflects the REVIEWED decision street, NOT the final
    all-in / showdown street. Order of trust: analyst `street` -> an explicit
    'PF ALL-IN'/'preflop' marker in the spot -> a preflop all-in (the all-in
    WAS preflop, so this is not final-street inference). Unknown -> neutral
    'Punt (analyst)' so a preflop punt is never mislabelled 'Postflop'."""
    cmt = cmt if isinstance(cmt, dict) else {}
    st = (cmt.get('street') or '').strip().lower()
    if st.startswith('pre') or st == 'pf':
        return 'Preflop punt (analyst)'
    if st in ('flop', 'turn', 'river', 'postflop'):
        return 'Postflop punt (analyst)'
    spot = (cmt.get('spot') or '').upper()
    if 'PF ALL-IN' in spot or 'PREFLOP' in spot:
        return 'Preflop punt (analyst)'
    if h and h.get('pf_allin'):
        return 'Preflop punt (analyst)'
    return 'Punt (analyst)'


def _emit_mental_game(doc, s, rd, hands):
    """Mental game analysis derived from session metrics."""
    # B55 (v7.47, Ron 2026-05-12): use analyst-overridden punt count.
    # Previously: `s.get('punts', {}).get('count', 0)` used raw stats and
    # produced "0 punts across N hands" even when analyst classified
    # hands as III.1 punts (creating a 0/2/2 discrepancy between Mental
    # Game (II.4), Strategic Eval header (III), and TL;DR). Matches the
    # surviving_auto_punts | analyst_iii1_ids pattern used elsewhere.
    auto_punts = s.get('punts', {}).get('hands', []) or []
    analyst_pre = (rd.get('analyst_commentary') or {})
    analyst_iii1_ids = {hid for hid, cmt in analyst_pre.items()
                        if isinstance(cmt, dict)
                        and cmt.get('verdict', '').startswith('III.1')}
    analyst_override_ids = {hid for hid, cmt in analyst_pre.items()
                             if isinstance(cmt, dict)
                             and cmt.get('verdict', '').startswith(_PUNT_OVERRIDE_PREFIXES)}
    auto_punt_ids = {p.get('id') for p in auto_punts}
    surviving_auto_punts = auto_punt_ids - analyst_override_ids
    punts = len(surviving_auto_punts | analyst_iii1_ids)
    rev = rd.get('reviewed_mistakes', {})
    # v7.39: confirmed = CLEAR survivors only (matches TL;DR + III + XIII.4 semantics)
    raw_mistakes = s.get('mistakes', [])
    needs_keys = {(m.get('id'), m.get('type')) for m in (rev.get('needs_review') or [])}
    auto_keys = {(m.get('id'), m.get('type')) for m in (rev.get('auto_corrected') or [])}
    # B173 (Ron 2026-05-24): exclude analyst-cleared III.0/III.3/4/5 hands — same
    # netting XIII.4.1 and the III header now apply, so this rate agrees.
    _ac_conf = (rd.get('analyst_commentary') or {})
    _override_conf = {hid for hid, cmt in _ac_conf.items()
                      if isinstance(cmt, dict)
                      and cmt.get('verdict', '').startswith(_MISTAKE_CLEARED_PREFIXES)}
    confirmed = sum(1 for m in raw_mistakes
                    if (m.get('id'), m.get('type')) not in needs_keys
                    and (m.get('id'), m.get('type')) not in auto_keys
                    and m.get('id') not in _override_conf
                    and (m.get('confidence', '') or '').upper() == 'CLEAR')
    n_hands = len(hands)
    # B222 (Ron review 2026-05-25): the "Mistakes/100" positive-signal line
    # must use the canonical confirmed-mistake count (= III.2 Confirmed
    # Mistakes / XIII.4 = detector CLEAR + analyst-confirmed III.1/III.2), not
    # the detector-only CLEAR count above.
    _dt_conf = (rd.get('discipline_tier', {}) or {})
    confirmed_canonical = _dt_conf.get('canonical_mistakes_count', confirmed)
    mistakes_per_100 = _dt_conf.get(
        'canonical_mistakes_per_100',
        (100.0 * confirmed_canonical / n_hands) if n_hands else 0)
    arc = s.get('intra_session_arc', {})
    tilt_flag = arc.get('tilt_flag', False)
    tilt_note = arc.get('tilt_note', '')

    # Phase 4.8: only show "Positive signals" block if there ARE positive signals.
    # User review: "no need for 'Positive signals: 0 punts...' if we have nothing to say"
    _pos_items = []
    if punts == 0:
        _pos_items.append(f"0 punts across {n_hands} hands — emotional control intact")
    if mistakes_per_100 < 1.5:
        _pos_items.append(f"Mistakes/100 at {mistakes_per_100:.2f} — within mid-stakes-reg expected band")
    if _pos_items:
        doc.w("**Positive signals:**")
        doc.w("")
        for _pi in _pos_items:
            doc.w(f"- {_pi}")
        doc.w("")
    if tilt_flag:
        doc.w("**Concerning signals:**")
        doc.w("")
        if tilt_note:
            doc.w(f"- {tilt_note}")
        else:
            doc.w("- 🔴 Late-session quartile shows mistakes/100 + bb/100 deterioration "
                  "vs early quartiles. See I.9 for quartile breakdown.")
        doc.w("")
    if not tilt_flag and not _pos_items:
        doc.w("*No mental-game red flags detected this session.*")
        doc.w("")
    doc.w("*Pre-session mantra (per memory): name the population frequency being exploited "
          "BEFORE any non-standard river action.*")
    doc.w("")
    # Batch 5 (4A): "What should I study" — prioritized 3-item action list
    _study_items = []
    _wl = rd.get('leak_watchlist', {})
    _top_red = [a for a in (_wl.get('top_actions') or []) if a.get('status') == 'red'][:2]
    for _tr in _top_red:
        _sec = _tr.get('section', '')
        _sec_link = f' ({_xref(_sec)})' if _sec else ''
        _study_items.append(f"Review {_tr.get('label', '?')} hands{_sec_link} — {_tr.get('action', '')}")
    # Add top drill if available
    _drills = rd.get('pre_session_drills') or rd.get('drill_script') or []
    if _drills and isinstance(_drills, list) and _drills:
        _d = _drills[0]
        _dname = _d.get('text', _d) if isinstance(_d, dict) else str(_d)
        _study_items.append(f"Practice drill: {_dname[:60]}")
    if _study_items:
        doc.w(f"**Before your next session:**{_new_badge('what_to_study')}")
        doc.w("")
        for _si_idx, _si in enumerate(_study_items[:3], 1):
            doc.w(f"{_si_idx}. {_si}")
        doc.w("")

    # ---- WIRING: Sizing tell ----
    _st = s.get('sizing_tell', {})
    if _st.get('is_tell'):
        doc.w(f"**Sizing tell detected:**{_new_badge('sizing_tell')} {_st['note']}. "
              f"Opponents can exploit this — vary your bet sizes.")
        doc.w("")

    # ---- WIRING: Tilt cascades ----
    _tc = s.get('tilt_cascades', [])
    if _tc:
        doc.w(f"**Tilt cascade{'s' if len(_tc) > 1 else ''} detected**{_new_badge('tilt_cascade')} "
              f"({len(_tc)} spike{'s' if len(_tc) > 1 else ''} "
              f"in mistake density after big losses):")
        doc.w("")
        for _tci in _tc[:3]:
            _trigger = _hand_ref(s['_hands_by_id'].get(_tci['trigger_id'])) if _tci.get('trigger_id') and s.get('_hands_by_id') else _tci.get('trigger_id', '?')
            doc.w(f"- After {_tci['trigger_loss_bb']:+.0f}BB loss ({_trigger}): "
                  f"{_tci['mistakes_in_window']} mistakes in next 20 hands "
                  f"({_tci['window_net_bb']:+.0f}BB window)")
        doc.w("")

    # ---- WIRING: Lucky mistakes (positive variance masking errors) ----
    _lm = s.get('lucky_mistakes', [])
    if _lm:
        doc.w(f"**All-ins won with low equity**{_new_badge('lucky_mistakes')} ({len(_lm)} hands won "
              f"despite <35% multiway equity — variance, not necessarily mistakes):")
        doc.w("")
        for _lmi in _lm[:5]:
            _lm_h = s.get('_hands_by_id', {}).get(_lmi['id'])
            _lm_ref = _hand_ref(_lm_h) if _lm_h else f"`{_lmi['id'][-8:]}`"
            doc.w(f"- {_lm_ref}: won {_lmi['net_bb']:+.1f}BB with "
                  f"{_lmi['equity_pct']:.0f}% equity ({_cards_str_to_pills(_lmi['cards'])})")
        doc.w("")

    # ---- WIRING: Overfold by position ----
    _of = s.get('overfold_by_position', [])
    if _of:
        doc.w(f"**Over-folding by position**{_new_badge('overfold')} (total fold rate >10pp above expected VPIP baseline):")
        doc.w("")
        for _ofi in _of[:4]:
            doc.w(f"- {_ofi['position']}: fold {_ofi['fold_pct']:.0f}% "
                  f"(expected ~{_ofi['expected_fold_pct']:.0f}%, "
                  f"+{_ofi['excess_pp']:.0f}pp excess, n={_ofi['sample']})")
        doc.w("")

    # ---- WIRING: What-if folds ----
    _wif = s.get('what_if_folds', [])
    if _wif:
        doc.w(f"<details><summary><strong>What-if folds</strong>{_new_badge('what_if_folds')} — {len(_wif)} hands "
              f"where Hero folded but would have had >70% equity</summary>")
        doc.w("")
        doc.w("*Not mistakes — just interesting context. Don't results-orient from these.*")
        doc.w("")
        for _wi in _wif[:5]:
            doc.w(f"- {_wi['note']}")
        doc.w("")
        doc.w("</details>")
        doc.w("")

    # ---- WIRING: Detector calibration summary ----
    _dc = s.get('detector_calibration', {})
    _noisy = {k: v for k, v in _dc.items() if v.get('status') == 'noisy'}
    if _noisy:
        doc.w(f"<details><summary><strong>Noisy detectors</strong>{_new_badge('detector_calibration')} — "
              f"{len(_noisy)} detectors with <40% analyst confirmation rate</summary>")
        doc.w("")
        doc.w("| Detector | Flagged | Confirmed | Cleared | Precision |")
        doc.w("|---|---|---|---|---|")
        for dname, ddata in sorted(_noisy.items(), key=lambda x: x[1].get('precision', 0) or 0):
            _prec = f"{ddata['precision']*100:.0f}%" if ddata.get('precision') is not None else '?'
            doc.w(f"| {dname} | {ddata['flagged']} | {ddata['confirmed']} | "
                  f"{ddata['cleared']} | {_prec} |")
        doc.w("")
        doc.w("*These detectors are historically noisy. Treat their flags as candidates, not confirmed.*")
        doc.w("</details>")
        doc.w("")

    # ---- WIRING: Missed bluff-raises (BUG-U) ----
    _mbr = s.get('missed_bluff_raises', [])
    if _mbr:
        doc.w(f"**Missed bluff-raise opportunities**{_new_badge('missed_bluff')} "
              f"({len(_mbr)} spots where Hero called with zero showdown value "
              f"— consider raising for fold equity):")
        doc.w("")
        for _mbri in _mbr[:5]:
            _mbr_h = s.get('_hands_by_id', {}).get(_mbri['id'])
            _mbr_ref = _hand_ref(_mbr_h) if _mbr_h else f"`{_mbri['id'][-8:]}`"
            doc.w(f"- {_mbr_ref}: {_mbri['note']} ({_mbri['net_bb']:+.1f} BB)")
        doc.w("")

    doc.w("")


# ============================================================
# SECTION III — STRATEGIC EVALUATION
# ============================================================

def _emit_iii_punts_mistakes(doc, s, rd, hands):
    """S2 — Section III header + E2 type summary + III.1 Punts + III.2 Confirmed Mistakes."""
    # v7.39: header count uses the same CLEAR-only logic as TL;DR + XIII.4 so
    # the three places agree. Previously this used `rev.get('confirmed')` which
    # was the reviewer-survivors count (CLEAR + MARGINAL combined), inflating
    # the headline number relative to what XIII.4.1 actually showed.
    rev = rd.get('reviewed_mistakes', {})
    raw_mistakes = s.get('mistakes', [])
    raw_n = len(raw_mistakes)
    needs_review_list = rev.get('needs_review', []) or []
    auto_corrected_list = rev.get('auto_corrected', []) or []
    needs_keys = {(m.get('id'), m.get('type')) for m in needs_review_list}
    auto_keys = {(m.get('id'), m.get('type')) for m in auto_corrected_list}
    survivors = [m for m in raw_mistakes
                 if (m.get('id'), m.get('type')) not in needs_keys
                 and (m.get('id'), m.get('type')) not in auto_keys]
    # B42 fix (v7.44): III header punt count must respect analyst overrides,
    # matching the TL;DR's surviving_auto_punts | analyst_iii1_ids logic. Was
    # using raw s['punts']['count'] which ignores analyst reclassification.
    raw_punts_list = s.get('punts', {}).get('hands', [])
    _analyst_pre = (rd.get('analyst_commentary') or {})
    _analyst_iii1 = {hid for hid, cmt in _analyst_pre.items()
                     if isinstance(cmt, dict) and cmt.get('verdict','').startswith('III.1')}
    _analyst_override = {hid for hid, cmt in _analyst_pre.items()
                         if isinstance(cmt, dict)
                         and cmt.get('verdict','').startswith(_MISTAKE_CLEARED_PREFIXES)}
    # B173 (Ron 2026-05-24): an analyst-cleared hand is not a confirmed
    # mistake — net it out of survivors BEFORE the CLEAR/MARGINAL counts,
    # so the III header agrees with XIII.4.1 and the headline count.
    if _analyst_override:
        survivors = [m for m in survivors
                     if m.get('id') not in _analyst_override]
    clear_n = sum(1 for m in survivors if (m.get('confidence', '') or '').upper() == 'CLEAR')
    marginal_n = sum(1 for m in survivors if (m.get('confidence', '') or '').upper() == 'MARGINAL')
    _auto_punt_ids = {p.get('id') for p in raw_punts_list}
    # v8.20 W1A.1 BUG-2: the punt count subtracts _PUNT_OVERRIDE_PREFIXES (includes III.2), NOT the
    # cleared set (_analyst_override) used for the mistake survivors above — an auto-punt the analyst
    # reclassifies to a confirmed mistake (III.2) is no longer a punt; counting it in both is the
    # 'X confirmed + 1 punts' double-count. Agrees with the TL;DR + discipline_tier canonical count.
    _punt_override = {hid for hid, cmt in _analyst_pre.items()
                      if isinstance(cmt, dict)
                      and cmt.get('verdict', '').startswith(_PUNT_OVERRIDE_PREFIXES)}
    punts = len((_auto_punt_ids - _punt_override) | _analyst_iii1)
    # v7.39 (Ron's request 2026-05-09): #/100 alongside absolute counts in the III
    # section header so the rates are visible without flipping to TL;DR or II.3.
    n_h = len(hands) or 1
    # B222 (Ron review 2026-05-25): the Section III header "🔴 confirmed"
    # count must match III.2 Confirmed Mistakes (8), not the detector-only
    # CLEAR survivor count (clear_n). Use the canonical discipline_tier field.
    _iii_conf = (rd.get('discipline_tier', {}) or {})
    _confirmed_hdr = _iii_conf.get('canonical_mistakes_count', clear_n)
    # Item 5: explicit PUNTS/100 and MISTAKES/100 labels, .2f formatting
    summary_bits = [f"PUNTS/100: {100.0*punts/n_h:.2f} ({punts})",
                    f"MISTAKES/100: {100.0*_confirmed_hdr/n_h:.2f} ({_confirmed_hdr} 🔴 confirmed)"]
    if marginal_n:
        summary_bits.append(f"{marginal_n} 🟡 marginal ({100.0*marginal_n/n_h:.2f}/100)")
    summary_bits.append(f"raw {raw_n} = {100.0*raw_n/n_h:.2f}/100")
    doc.section("sec-2", "S2. Strategic Evaluation (Error Taxonomy)",
                " | ".join(summary_bits))

    # E2 (Ron 2026-05-11): after the section header counts, list the actual
    # confirmed mistake types so the reader doesn't see just "6 🔴 confirmed"
    # with no description. Pull from the surviving CLEAR mistakes plus
    # analyst-confirmed III.1s.
    raw_mist_iii = stats.get('mistakes', []) or [] if False else s.get('mistakes', []) or []
    rev_iii = rd.get('reviewed_mistakes', {}) or {}
    needs_keys = {(m.get('id'), m.get('type')) for m in (rev_iii.get('needs_review') or [])}
    auto_keys = {(m.get('id'), m.get('type')) for m in (rev_iii.get('auto_corrected') or [])}
    survivors = [m for m in raw_mist_iii
                 if (m.get('id'), m.get('type')) not in needs_keys
                 and (m.get('id'), m.get('type')) not in auto_keys]
    # B173 (Ron 2026-05-24): drop analyst-cleared III.0/III.3/4/5 hands from the
    # confirmed-mistake type-summary too — keeps it consistent with the header.
    _ac_iii = (rd.get('analyst_commentary') or {})
    _override_iii = {hid for hid, cmt in _ac_iii.items()
                     if isinstance(cmt, dict)
                     and cmt.get('verdict', '').startswith(_MISTAKE_CLEARED_PREFIXES)}
    clear_survivors = [m for m in survivors
                       if (m.get('confidence','') or '').upper() == 'CLEAR'
                       and m.get('id') not in _override_iii
                       and not ('Missed Steal' in (m.get('type','') or ''))]
    if clear_survivors:
        # Group by mistake type for the summary
        from collections import Counter as _Counter
        type_counts = _Counter(m.get('type','—').split('(')[0].strip() for m in clear_survivors)
        type_summary_parts = []
        for typ, cnt in type_counts.most_common(5):
            type_summary_parts.append(f"{cnt}× {typ}")
        doc.w(f"**Confirmed mistakes** ({len(clear_survivors)}): "
              f"{', '.join(type_summary_parts)}. "
              f"See [Confirmed Mistakes ↓](#sec-17-4-confirmed) for full list with hand links.")
        doc.w("")

    # Issue 10 (Ron 2026-05-30): Surface passivity-leak headline so a low
    # confirmed-count can't be read as "clean" when aggregate passivity signals
    # are loud. These counts include ALL confidence tiers (CLEAR + MARGINAL)
    # and needs_review — they show the full detector picture, not just the
    # headline-eligible survivors.
    _all_mist = s.get('mistakes', []) or []
    _pass_steals = sum(1 for m in _all_mist if 'Missed Steal' in (m.get('type','') or ''))
    _pass_shoves = sum(1 for m in _all_mist
                       if 'Missed Push' in (m.get('type','') or '')
                       or 'Missed Reshove' in (m.get('type','') or ''))
    _pass_dcbet = sum(1 for m in _all_mist
                      if 'Missed Turn Delayed C-bet' in (m.get('type','') or ''))
    _pass_total = _pass_steals + _pass_shoves + _pass_dcbet
    if _pass_total >= 5:
        _pass_parts = []
        if _pass_steals:
            _pass_parts.append(f"{_pass_steals} missed steals")
        if _pass_shoves:
            _pass_parts.append(f"{_pass_shoves} missed shoves")
        if _pass_dcbet:
            _pass_parts.append(f"{_pass_dcbet} missed delayed c-bets")
        doc.w(f"**Passivity flags** ({_pass_total}): "
              f"{', '.join(_pass_parts)} — "
              f"these include MARGINAL/needs-review and do not reach the confirmed count above. "
              f"See S4.2 Out-of-Bound Leak Discovery for deviation rates.")
        doc.w("")

    # III.1 Range Oblivion / Punts
    # B103 (Ron 2026-05-19): inject hand count into III.1 header so the
    # subsection title shows how many hands are being showcased.
    _p_pre = s.get('punts', {})
    _analyst_pre_for_count = rd.get('analyst_commentary', {}) or {}
    # (prefix constants defined at module level: _PUNT_OVERRIDE_PREFIXES,
    #  _MISTAKE_CLEARED_PREFIXES)
    _analyst_iiix_override_pre = {hid for hid, cmt in _analyst_pre_for_count.items()
                                  if isinstance(cmt, dict)
                                  and cmt.get('verdict','').startswith(_PUNT_OVERRIDE_PREFIXES)}
    _auto_n_pre = len([ph for ph in _p_pre.get('hands', [])
                       if ph.get('id') not in _analyst_iiix_override_pre])
    _analyst_iii1_n_pre = len([hid for hid, cmt in _analyst_pre_for_count.items()
                               if isinstance(cmt, dict) and cmt.get('verdict','').startswith('III.1')])
    _auto_ids_pre = {ph.get('id') for ph in _p_pre.get('hands', [])
                     if ph.get('id') not in _analyst_iiix_override_pre}
    _analyst_only = len([hid for hid, cmt in _analyst_pre_for_count.items()
                         if isinstance(cmt, dict) and cmt.get('verdict','').startswith('III.1')
                         and hid not in _auto_ids_pre])
    _total_iii1 = _auto_n_pre + _analyst_only
    doc.subsection("sec-2-1", "S2.1 Range Oblivion / Punts",
                   f"fundamental blunders, dominated stack-offs — "
                   f"{_total_iii1} hand{'s' if _total_iii1 != 1 else ''}")
    p = s.get('punts', {})
    # v7.43 (2026-05-09): augment auto-detected punts with analyst-classified
    # III.1 bust hands. Auto-detector catches preflop pattern punts (P6 etc);
    # analyst catches postflop punts (turn-jam without fold equity, river
    # over-call vs polarized big bets) that pattern-detection misses.
    # ALSO (Ron 2026-05-09): suppress auto-detected punts when analyst
    # classified that hand as III.0/III.3/III.4/III.5 — Ron's reclassification
    # overrides the auto-detector when there's an explicit verdict.
    analyst_pre = rd.get('analyst_commentary', {}) or {}
    analyst_iii1_ids = [hid for hid, cmt in analyst_pre.items()
                        if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.1')]
    analyst_iiix_override = {hid for hid, cmt in analyst_pre.items()
                             if isinstance(cmt, dict)
                             and cmt.get('verdict','').startswith(_PUNT_OVERRIDE_PREFIXES)}
    auto_punt_hands_filtered = [ph for ph in p.get('hands', [])
                                if ph.get('id') not in analyst_iiix_override]
    auto_punt_ids = {ph.get('id') for ph in auto_punt_hands_filtered}
    hands_by_id_ix = {h.get('id', ''): h for h in hands}

    auto_punt_by_id = {ph.get('id'): ph for ph in auto_punt_hands_filtered}

    # B148 (v7.71, Ron 2026-05-23): the punt detector is a backend efficiency
    # process — it surfaces candidates, it is NOT the user-facing verdict.
    # Every III.1 row must carry the ANALYST's verdict + commentary. Two bugs
    # this fixes:
    #   (1) a detector punt that DID have an analyst III.1 verdict still
    #       rendered through the detector loop as "auto-detector", hiding the
    #       analyst commentary entirely (the analyst-only loop skip-continued
    #       on `hid in auto_punt_ids`). Ron: 86806424 should show analyst
    #       comment, not "Flagged as a punt by the detector".
    #   (2) the III.1 section count and the TL;DR "Confirmed punts" count
    #       diverged (3 vs 1) because detector-flagged-but-unreviewed punts
    #       padded the section but not the TL;DR. Once every detector punt is
    #       analyst-reviewed (pipeline now routes them into analyst_candidates
    #       ['punts']), both counts agree by construction.
    # A detector punt with NO analyst verdict is an analyst-process GAP — it
    # is surfaced loudly ("⚠ awaiting analyst review"), never normalised as a
    # routine "auto-detector" source.
    # Render order: detector-flagged first (stable input order), then
    # analyst-only classifications.
    iii1_ids = []
    for ph in auto_punt_hands_filtered:
        if ph.get('id') and ph['id'] not in iii1_ids:
            iii1_ids.append(ph['id'])
    for hid in analyst_iii1_ids:
        if hid not in iii1_ids:
            iii1_ids.append(hid)

    if not iii1_ids:
        doc.w("✅ No punts confirmed (auto-detector findings overridden by "
              "analyst, no analyst punt verdicts).")
    else:
        # v8.20 W1A.2 V820-QA-013: the value is the hand's REALIZED net (h['net_bb']), not a canonical
        # decision-EV. Label it 'Hand net'; 'EV' is reserved for a persisted calculation record.
        _m1_hdr = "| Hand Reference | Cards | Type | Hand net | Source |"
        _m1_sep = "|---|---|---|---|---|"
        _m1_rows = []
        for hid in iii1_ids:
            cmt = analyst_pre.get(hid)
            cmt = cmt if isinstance(cmt, dict) else None
            ph = auto_punt_by_id.get(hid)
            h = hands_by_id_ix.get(hid)
            if ph:
                href = _href(ph, s['_hands_by_id'])
                cards = _real_cards_pills(ph, s['_hands_by_id'])
            elif h:
                href = _hand_ref(h)
                cards = _cards_str_to_pills(''.join(h.get('cards', []))) or '—'
            else:
                href = f"`{hid[-8:]}`"
                cards = '—'
            if cmt and cmt.get('verdict', '').startswith('III.1'):
                # Analyst-reviewed punt — the analyst verdict IS the record.
                spot = cmt.get('spot', '')
                # B37: split on '. ' (period-space) so decimals like "31.6BB"
                # don't break the label; fall back to first 80 chars.
                if spot:
                    type_label = (spot.split('. ')[0][:80]
                                  if '. ' in spot else spot[:80])
                else:
                    type_label = _analyst_punt_street_label(cmt, h)
                ev_str = (f"{h.get('net_bb', 0):+.1f} BB" if h
                          else (ph.get('ev', '—') if ph else '—'))
                source = 'analyst'
            else:
                # Detector flag with no analyst verdict — process gap. Flag it
                # loudly; do NOT present the detector as a finished verdict.
                type_label = ph.get('type', '—') if ph else '—'
                ev_str = (ph.get('ev', '—') if ph
                          else (f"{h.get('net_bb', 0):+.1f} BB" if h else '—'))
                # BUG-7: suppress loud "awaiting analyst" in published reports
                source = '⚪ detector flag (pending review)'
            _m1_rows.append(f"| {href} | {cards} | {type_label} | {ev_str} | {source} |")
        _m1_blk = hand_evidence_table_block("iii1-punts", _m1_hdr, _m1_sep, _m1_rows)
        doc.write_block(_m1_blk)
        doc.w("")
        # Note suppressed auto-punts (transparency)
        # Bug 3 fix (Ron 2026-05-30): reword so analyst verdict is PRIMARY
        # and detector tag is clearly historical — prevents the old
        # "Punt (P6-...) → III.4" phrasing that reads as a still-active
        # mistake tag.  Also: skip hands cleared to III.8 (Picks) here —
        # they render in S4.3 Pokerbot's Picks; showing them in both
        # a punt note and a Picks section was confusing reviewers.
        _VERDICT_SHORT = {
            'III.0': 'cleared',
            'III.2': 'confirmed mistake',
            'III.3': 'variance / cooler',
            'III.4': 'read-dependent',
            'III.5': 'justified',
            'III.8': 'pick',
            'I.7':   'cooler',
        }
        suppressed = [ph for ph in p.get('hands', [])
                      if ph.get('id') in analyst_iiix_override]
        if suppressed:
            doc.w(f"*Note: {len(suppressed)} auto-detected punt(s) suppressed by analyst override "
                  f"(reclassified by analyst):*")
            for ph in suppressed:
                cmt = analyst_pre.get(ph.get('id'), {})
                v = cmt.get('verdict', '?')
                # B188 (Ron 2026-05-25): was a dead `id` code-span — a mentioned
                # hand must always link. _href links it (deep-harvest guarantees
                # the id is in the appendix set).
                ref = _href(ph, s['_hands_by_id'])
                # Bug 3: verdict-primary wording — e.g.
                #   "→ reclassified III.4 read-dep (was auto-flagged P6-BluffOverbet)"
                _vshort = ''
                for _vp, _vl in _VERDICT_SHORT.items():
                    if v.startswith(_vp):
                        _vshort = f" {_vl}"
                        break
                _det_tag = ph.get('type', '—')
                # Obj-H: III.1 isn't in _VERDICT_SHORT; strip the code so the
                # fallback reads "Punt", never the raw "III.1 Punt".
                _vlabel = _vshort.strip() if _vshort else _verdict_display_label(v)
                doc.w(f"- {ref} ({_cards_str_to_pills(ph.get('cards','—'))}) "
                      f"→ reclassified as {_vlabel} (was auto-flagged {_det_tag})")
            doc.w("")
        # B97 (Ron 2026-05-19): removed "Analyst notes on III.1 punts" section.
        # It was duplicative of the hand examples (per-hand annotations) already
        # rendered in the III.1 Punts table earlier in this same section.
    doc.w("")

    # ============================================================
    # III.2 Confirmed Mistakes (B210, Ron review 2026-05-25)
    # ============================================================
    # The confirmed-mistakes table used to live at XIII.4.1, buried near the
    # bottom — Ron: "it's one of the most important things and it's buried;
    # put it right after the punts." Surfaced here as its own section. The
    # full per-subsection mistake breakdown still lives in XIII.4; this is the
    # headline ledger. Source: detector CLEAR-confidence mistakes + analyst
    # III.1/III.2 verdicts (the B208 ledger), deduplicated by hand id.
    _cm_mistakes = s.get('mistakes', []) or []
    _cm_analyst = rd.get('analyst_commentary', {}) or {}
    _cm_rev = rd.get('reviewed_mistakes', {}) or {}
    _cm_needs = {(m.get('id'), m.get('type')) for m in (_cm_rev.get('needs_review') or [])}
    _cm_auto = {(m.get('id'), m.get('type')) for m in (_cm_rev.get('auto_corrected') or [])}
    # CLEAR-confidence detector mistakes that survived review (not needs-review,
    # not auto-corrected, not analyst-overridden to III.0/III.3/III.4/III.5).
    _cm_clear = []
    for m in _cm_mistakes:
        if (m.get('confidence', '') or '').upper() != 'CLEAR':
            continue
        key = (m.get('id'), m.get('type'))
        if key in _cm_needs or key in _cm_auto:
            continue
        v = (_cm_analyst.get(m.get('id'), {}) or {})
        vv = (v.get('verdict', '') or '') if isinstance(v, dict) else ''
        if vv.startswith(_MISTAKE_CLEARED_PREFIXES):
            continue  # analyst cleared / reclassified — not a confirmed mistake
        _cm_clear.append(m)
    _cm_clear_ids = {m.get('id') for m in _cm_clear}
    _cm_detector_ids = {m.get('id') for m in _cm_mistakes}
    # B258 FIX: analyst III.1/III.2 verdicts count as confirmed mistakes
    # even if the hand had a detector flag. Only exclude CLEAR survivors
    # (already counted in _cm_clear). Removed `and hid not in _cm_detector_ids`.
    _cm_analyst_only = [
        (hid, c) for hid, c in (_cm_analyst.items() if isinstance(_cm_analyst, dict) else [])
        if isinstance(c, dict) and (c.get('verdict', '') or '').startswith(('III.1', 'III.2'))
        and hid not in _cm_clear_ids]
    _cm_total_live = len(_cm_clear) + len(_cm_analyst_only)
    _cm_n_h = len(hands) or 1
    # P0 FIX: use CANONICAL count from discipline_tier (single source of truth
    # recomputed by _refresh_discipline_tier after analyst attach) so the S2.2
    # heading matches the TL;DR, stat strip, and S2 header. The live list
    # length is kept for the table rows below.
    _dt_p0 = (rd.get('discipline_tier') or {})
    _cm_total = _dt_p0.get('canonical_mistakes_count', _cm_total_live)
    # Phase 4.8 (user review S2.2 bug): rate should be confirmed mistakes + punts,
    # not just confirmed mistakes alone — user expects the combined error rate.
    _cm_punts = _dt_p0.get('canonical_punts_count', punts)
    _cm_combined = _cm_total + _cm_punts
    doc.subsection("sec-2-2", "S2.2 Confirmed Mistakes",
                   f"{_cm_total} confirmed + {_cm_punts} punts = "
                   f"{_cm_combined} errors ({100.0*_cm_combined/_cm_n_h:.2f}/100)")
    doc.w("*Decisions confirmed as mistakes — detector CLEAR-confidence flags "
          "the analyst did not clear, plus hands the analyst graded a punt or "
          "a strategic leak. Coolers, justified variance and read-dependent "
          "spots are excluded by design. This is the headline list; XIII.4 "
          "has the same hands plus the marginal/tail-fold/auto-corrected "
          "breakdown.*")
    doc.w("")
    if not _cm_total:
        doc.w("👍 No confirmed mistakes this session.")
        doc.w("")
    else:
        # v8.20 W1A.2 V820-QA-013: realized hand net, not a canonical decision-EV (see _m1_hdr).
        _m2_hdr = "| Hand Reference | Cards | What went wrong | Hand net | Source |"
        _m2_sep = "|---|---|---|---|---|"
        _m2_rows = []
        for m in _cm_clear:
            href = _href(m, s['_hands_by_id'])
            ev = m.get('estimated_ev_bb', m.get('ev', '—'))
            ev_str = f"{ev:+.1f} BB" if isinstance(ev, (int, float)) else str(ev)
            _m2_rows.append(f"| {href} | {_real_cards_pills(m, s['_hands_by_id'])} | {m.get('type','—')} | "
                  f"{ev_str} | detector |")
        for hid, c in _cm_analyst_only:
            h = (s.get('_hands_by_id', {}) or {}).get(hid, {})
            href = _href(h, s['_hands_by_id']) if h else f"`{hid[-8:]}`"
            cards = (_cards_str_to_pills(''.join(h.get('cards', []) or []))
                     if h else '—')
            ev = h.get('net_bb') if h else None
            ev_str = f"{ev:+.1f} BB" if isinstance(ev, (int, float)) else '—'
            # B211 (Ron 2026-05-25): show the concise human label, not the
            # bare "III.1"/"III.2" verdict code — "III.2" is not a description.
            _what = c.get('label') or {
                'III.1': 'Punt', 'III.2': 'Strategic leak'}.get(
                (c.get('verdict', '') or '')[:5], c.get('verdict', '—'))
            _m2_rows.append(f"| {href} | {cards} | {_what} | {ev_str} | analyst |")
        _m2_blk = hand_evidence_table_block("iii2-confirmed", _m2_hdr, _m2_sep, _m2_rows)
        doc.write_block(_m2_blk)
        doc.w("")
        doc.w(f"*Same hands, with the marginal / tail-fold / auto-corrected "
              f"breakdown: {_xref('sec-17-4', label='S17.4')}.*")
        doc.w("")

    # === Subsections gained from other sections ===
    # sec-1-3 Large-Loss Audit (from S1)
    from gem_report_draft.sections_financial import _emit_sub_large_loss_audit
    _emit_sub_large_loss_audit(doc, s, rd, hands)
    # sec-4-3 Pokerbot's Picks (from S4)
    _emit_sub_picks(doc, s, rd, hands)
    # Item 11: Read-Dependent + GTO-Standard subsegments after Picks
    _emit_sub_read_dep_picks(doc, s, rd, hands)
    _emit_sub_gto_standard_picks(doc, s, rd, hands)


def _emit_iii_strategic_leaks(doc, s, rd, hands):
    """S3 — III.3 Strategic Leaks (promoted leak detail + example hands)."""
    # ============================================================
    # III.3 Strategic Leaks (post promotion gate)  [renumbered III.2→III.3, B210]
    # ============================================================
    # v7.36c: Cross-Ref column now a real link via _xref. Each promoted leak
    # gets a III.3.N detail subsection with example hands + analyst judgment
    # pulled from analyst_commentary['__synthesis__']['leaks'][leak_name].
    persistence = rd.get('leak_persistence', {})
    promoted_pre = persistence.get('current_leaks', []) or persistence.get('new', [])
    _synth_pre = (rd.get('analyst_commentary', {}) or {}).get('__synthesis__', {})
    _leaks_cmt_pre = _synth_pre.get('leaks', {}) if isinstance(_synth_pre, dict) else {}
    _verdict_counts = {'real': 0, 'mixed': 0, 'noise': 0, 'pending': 0}
    for _leak in promoted_pre:
        _name = _leak if isinstance(_leak, str) else (
                _leak.get('name') or _leak.get('leak') or '')
        _ron_status = (_leaks_cmt_pre.get(_name, {}).get('real_or_noise') or '').lower()
        if 'real' in _ron_status: _verdict_counts['real'] += 1
        elif 'mixed' in _ron_status: _verdict_counts['mixed'] += 1
        elif 'noise' in _ron_status or 'justified' in _ron_status: _verdict_counts['noise'] += 1
        else: _verdict_counts['pending'] += 1
    if not promoted_pre:
        # P1: clarify — no promoted leaks, but IE may have candidate issues
        _n_ie = len(rd.get('issue_explorer_issues', []))
        _summary_str = (f"no promoted leaks — {_n_ie} candidate issues in Issue Explorer"
                        if _n_ie else "no metric-flagged leaks this session")
    else:
        _verdict_parts = []
        if _verdict_counts['real']: _verdict_parts.append(f"🔴 {_verdict_counts['real']} real")
        if _verdict_counts['mixed']: _verdict_parts.append(f"🟡 {_verdict_counts['mixed']} mixed")
        if _verdict_counts['noise']: _verdict_parts.append(f"🟢 {_verdict_counts['noise']} noise/justified")
        if _verdict_counts['pending']:
            _all_pending = (_verdict_counts['pending'] == sum(_verdict_counts.values()))
            if _all_pending:
                _verdict_parts.append(f"📊 {_verdict_counts['pending']} flagged")
            else:
                _verdict_parts.append(f"⚪ {_verdict_counts['pending']} pending")
        _summary_str = f"{len(promoted_pre)} metric-flagged ({', '.join(_verdict_parts)})"
    doc.section("sec-3", "S3. Strategic Leaks", _summary_str)
    promoted = promoted_pre
    csv = s.get('csv_row', {})
    core = s.get('core', {})
    cbet = s.get('cbet', {})

    # Map leak label → (backing detail string, target section anchor, label)
    def _leak_meta(name):
        n = name.lower()
        if 'aggressor' in n and 'reactor' in n:
            agg = core.get('agg_vs_reactor_delta_pct')
            base = (f"Aggressor pot-control gap: {agg:.1f}pp asymmetry"
                    if agg else "Aggressor-vs-Reactor asymmetry")
            return (base, 'sec-iii-5', 'Justified')
        if 'hu c-bet' in n or 'hu cbet' in n:
            ip_pct = csv.get('Flop_CBet_HU', 0)
            return (f"Flop HU C-Bet IP {ip_pct:.1f}% vs target 60-75% — overcbetting auto-pilot zone",
                    'sec-vi-1', 'VI.1')
        if 'non-sd win' in n or 'non sd' in n:
            nsd = csv.get('Non_SD_Win', core.get('non_sd_win', 0))
            return (f"Non-SD Win {nsd:.1f}% vs target 25-35% — bluff-attempt connect rate too low",
                    'sec-ii-2', 'II.2')
        if 'wtsd' in n:
            wtsd = csv.get('WTSD_Vol', 0)
            return (f"WTSD {wtsd:.1f}% vs target 25-32%", 'sec-ii-2', 'II.2')
        if 'cold call' in n:
            return ("Cold Call NB 50.0% vs target 5-15% — major NB-flat leak",
                    'sec-ii-2', 'II.2')
        if 'sb' in n and ('def' in n or 'fold' in n):
            return ("SB Defense vs LP 23.3% vs target 30-40%", 'sec-v-3', 'V.3')
        if 'bb iso' in n or 'sb limp' in n:
            return ("BB Iso vs SB Limp 33.3% vs target 65-85% — under-isolating",
                    'sec-ii-5', 'II.5')
        return ("see backing sections for stats", 'sec-ii-2', 'II.2')

    def _candidate_hands_for_leak(name, hands, s):
        """v7.42: programmatically extract candidate hands per leak type.

        Maps a leak name to the hands that drove its metric. Returns a list of
        {hand_id, context, why} dicts ranked by relevance (high-impact first).
        Returns [] when no programmatic mapping exists for this leak.

        This isn't analyst judgment — it's "show me the hands that built up
        this percentage" so Ron can review them without waiting for an LLM
        commentary pass.
        """
        n = name.lower()
        out = []

        if 'hu c-bet' in n or 'hu cbet' in n:
            # Hero IP HU c-bet at 80% vs target 60-75%. Surface the IP HU c-bets
            # where Hero was the PFR — every one is a contributor.
            # v7.42 fix: no bare 'cbet_flop' field exists in parsed hands —
            # cbet flag is split by pot type (srp/3bp/4bp/mw). HU = NOT
            # multiway_flop. IP = position not in SB/BB (approximate; precise
            # IP requires showdown_position or in_position field).
            for h in hands:
                if not h.get('pfr'): continue
                if h.get('multiway_flop'): continue  # MW excluded — HU only
                made_cbet = (h.get('cbet_flop_srp')
                             or h.get('cbet_flop_3bp')
                             or h.get('cbet_flop_4bp'))
                if not made_cbet: continue
                if h.get('position') in ('SB', 'BB'): continue  # OOP — skip
                stack = h.get('stack_bb') or 0
                pos = h.get('position', '?')
                cards_list = h.get('cards') or []
                cards = _cards_str_to_pills(''.join(cards_list)) if cards_list else '??'
                board = h.get('board', []) or []
                board_str = _cards_str_to_pills(' '.join(board[:3])) if board else '???'
                pot_type = h.get('pot_type', 'SRP')
                out.append({
                    'hand_id': h.get('id', ''),
                    'context': f"{pos} {stack:.0f}BB, {cards} on {board_str} ({pot_type})",
                    'why': "Hero IP HU c-bet (contributor to overall HU IP rate)",
                })
            return out

        if 'non-sd win' in n or 'non sd' in n:
            # Non-SD Win at 19% vs target 25-35%. Surface hands where Hero
            # made aggression but didn't win the pot without showdown — i.e.,
            # the hands where the bluff/probe failed or wasn't taken.
            # v7.42 fix: 'won_no_showdown' isn't a field; derive from went_to_sd
            # + won. Non-SD win = won AND NOT went_to_sd. Non-SD loss = NOT won
            # AND NOT went_to_sd. We surface non-SD-loss hands where Hero c-bet
            # (those are the failed-bluff candidates).
            for h in hands:
                if not h.get('vpip'): continue
                went_sd = h.get('went_to_sd')
                won = h.get('won')
                if went_sd: continue  # showdown hands aren't the leak
                if won: continue  # non-SD wins ARE the metric numerator, not contributors
                # Non-SD loss — Hero played the hand but didn't win without showdown
                made_cbet = (h.get('cbet_flop_srp')
                             or h.get('cbet_flop_3bp')
                             or h.get('cbet_flop_4bp')
                             or h.get('cbet_flop_mw'))
                stack = h.get('stack_bb') or 0
                pos = h.get('position', '?')
                cards_list = h.get('cards') or []
                cards = _cards_str_to_pills(''.join(cards_list)) if cards_list else '??'
                action_summary = h.get('action_summary', '') or ''
                if made_cbet:
                    out.append({
                        'hand_id': h.get('id', ''),
                        'context': f"{pos} {stack:.0f}BB, {cards}",
                        'why': f"Hero c-bet, didn't win without showdown — {action_summary[:60]}",
                    })
                    if len(out) >= 12: break
                elif h.get('pfr'):
                    # PFR'd but didn't c-bet AND didn't win non-SD — missed steal
                    out.append({
                        'hand_id': h.get('id', ''),
                        'context': f"{pos} {stack:.0f}BB, {cards}",
                        'why': f"Hero PFR'd, no c-bet, no non-SD win — {action_summary[:60]}",
                    })
                    if len(out) >= 12: break
            return out

        if 'aggressor' in n and 'reactor' in n:
            # Asymmetric aggression — surface hands where Hero was reactor
            # and folded with mid-strength
            for h in hands:
                if h.get('pfr'): continue  # Hero was aggressor, not reactor
                if not h.get('vpip'): continue
                if h.get('won_no_showdown'): continue
                action_summary = h.get('action_summary', '') or ''
                if 'fold' not in action_summary.lower(): continue
                stack = h.get('stack_bb') or 0
                pos = h.get('position', '?')
                cards = _cards_str_to_pills(h.get('hole_cards', '?'))
                out.append({
                    'hand_id': h.get('id', ''),
                    'context': f"{pos} {stack:.0f}BB, {cards}",
                    'why': f"Hero (reactor) folded — {action_summary[:50]}",
                })
                if len(out) >= 12: break
            return out

        # B39 fix (v7.45): SB Pot-Entry candidates — surface SB Missed Open
        # hands (CLEAR violations) which are the actual leak contributors per
        # the J29 framework (target 85-95% pot entry full-ring).
        if 'sb pot' in n or 'sb-pot' in n:
            sb_devs = [d for d in s.get('preflop_deviations', [])
                       if d.get('pos') == 'SB' and d.get('type') == 'Missed Open']
            # Sort: CLEAR first, then MARGINAL
            sb_devs.sort(key=lambda d: (d.get('confidence', '') != 'CLEAR',))
            for d in sb_devs[:12]:
                stack = d.get('stack_bb') or 0
                cards = _cards_str_to_pills(d.get('cards', '??'))
                conf = d.get('confidence', '?')
                # v8.8.6 S1: caveat CLEAR for satellite/ICM hands
                _d_fmt = (d.get('format') or '').upper()
                if _d_fmt == 'SATELLITE' and conf == 'CLEAR':
                    conf = 'CLEAR chipEV-only · SAT/ICM caveat'
                out.append({
                    'hand_id': d.get('id', ''),
                    'context': f"SB {stack:.0f}BB, {cards}",
                    'why': f"Missed open ({conf}) — J29 says limp/raise",
                })
            return out

        # B39 fix (v7.45): Caller IP Agg candidates — surface hands where
        # Hero called preflop, was IP postflop, and made NO postflop aggression
        # (passive in position). These are the misses that drag down Caller-IP-
        # Flop-Aggression rate.
        if 'caller ip' in n or 'caller-ip' in n:
            for h in hands:
                if h.get('pfr'): continue  # Hero was raiser, not caller
                if not h.get('vpip'): continue  # didn't even enter pot
                if h.get('position') in ('SB','BB'): continue  # OOP
                # Hero called pre AND saw flop AND made no aggression
                if len(h.get('board', [])) < 3: continue
                hero_bets = h.get('hero_bets', []) or []
                if any(b[0] in ('flop','turn','river') for b in hero_bets):
                    continue  # Hero DID make postflop aggression — not a contributor
                # Check it's actually heads-up or near-HU (not big multiway)
                stack = h.get('stack_bb') or 0
                pos = h.get('position', '?')
                cards_list = h.get('cards') or []
                cards = _cards_str_to_pills(''.join(cards_list)) if cards_list else '??'
                action_summary = h.get('action_summary', '') or ''
                out.append({
                    'hand_id': h.get('id', ''),
                    'context': f"{pos} {stack:.0f}BB, {cards}",
                    'why': f"Hero called pre IP, no postflop agg — {action_summary[:55]}",
                })
                if len(out) >= 12: break
            return out

        # Default: no programmatic extraction available for this leak type
        return []

    if not promoted:
        doc.w("⚪ No leaks passed the promotion gate this session.")
        doc.w("")
    else:
        # Ron 2026-05-11: lead with a plain-language framing so reader knows
        # whether to act. When everything's been judged 🟢 noise, the table
        # exists for audit transparency — not for action items.
        if _verdict_counts['real'] == 0 and _verdict_counts['mixed'] == 0 and _verdict_counts['pending'] == 0:
            doc.w("✅ **All flagged leaks judged noise/justified — no action items.** "
                  "The table below shows what metric-tripped this session and the "
                  "analyst's reasoning for dismissing each, kept for audit transparency.")
        elif _verdict_counts['real']:
            doc.w(f"🔴 **{_verdict_counts['real']} confirmed real leak"
                  f"{'s' if _verdict_counts['real']>1 else ''} this session** "
                  f"— see Status column for which ones, and expand the matching "
                  f"S3.N detail block for example hands.")
        elif _verdict_counts['pending']:
            # When ALL leaks are pending, it means no analyst pass was run.
            # Don't alarm the user — these are metric flags, not confirmed leaks.
            _all_pending = (_verdict_counts['pending'] == sum(_verdict_counts.values()))
            if _all_pending:
                doc.w(f"📊 **{_verdict_counts['pending']} metric-flagged pattern"
                      f"{'s' if _verdict_counts['pending']>1 else ''}** "
                      f"— detected by frequency deviation. Monitor over multiple "
                      f"sessions before treating as confirmed leaks.")
            else:
                doc.w(f"⚪ **{_verdict_counts['pending']} leak"
                      f"{'s' if _verdict_counts['pending']>1 else ''} "
                      f"flagged, pending analyst review.**")
        else:
            doc.w(f"🟡 **{_verdict_counts['mixed']} leak"
                  f"{'s' if _verdict_counts['mixed']>1 else ''} judged mixed** "
                  f"— partial evidence either way, monitor next session.")
        doc.w("")
        # D2 (Ron 2026-05-11): merge summary + metric + analyst judgment into
        # ONE table; per-leak detail moves to collapsible <details> blocks.
        synth = (rd.get('analyst_commentary', {}) or {}).get('__synthesis__', {})
        leaks_commentary = synth.get('leaks', {}) if isinstance(synth, dict) else {}
        doc.w(f"| # | Leak | Metric | EV Impact{_new_badge('ev_impact')} | Status | Analyst Judgment | Detail |")
        doc.w("|---|---|---|---|---|---|---|")
        leak_xrefs = {}
        for i, leak in enumerate(promoted, 1):
            if isinstance(leak, dict):
                name = leak.get('name', leak.get('leak', '—'))
            else:
                name = str(leak)
            detail, anchor, label = _leak_meta(name)
            self_anchor = f"sec-3-{i}"
            leak_xrefs[name] = (self_anchor, anchor, label)
            cmt = leaks_commentary.get(name, {})
            metric_str = cmt.get('metric_summary') or detail
            judgment = cmt.get('judgment') or '—'
            ron_status = (cmt.get('real_or_noise') or '').lower()
            _status_map = {'real': '🔴 real', 'mixed': '🟡 mixed',
                           'noise': '🟢 noise', 'noise/justified': '🟢 noise'}
            if ron_status in _status_map:
                status_tag = _status_map[ron_status]
            elif not leaks_commentary:
                # No analyst pass at all — show neutral "flagged" not "pending"
                status_tag = '📊 flagged'
            else:
                status_tag = '⚪ pending'
            # B169 (anti-blob): judgment is now structured multi-line markdown;
            # take the first callout line, strip newlines, for the terse cell.
            _jcell = judgment.split('\n')[0].strip()
            judg_short = _jcell if len(_jcell) < 120 else _jcell[:115] + '…'
            # Batch 3 (#3): EV impact — sum net_bb of candidate hands for this leak
            _leak_cands = _candidate_hands_for_leak(name, hands, s)
            _hands_by_id_s3 = s.get('_hands_by_id') or {}
            _ev_total = 0.0
            _ev_count = 0
            for _lc in _leak_cands:
                _lc_h = _hands_by_id_s3.get(_lc.get('hand_id', ''), {})
                _lc_net = _lc_h.get('net_bb', 0) if _lc_h else 0
                _ev_total += _lc_net
                _ev_count += 1
            _ev_cell = f"{_ev_total:+.0f} BB ({_ev_count})" if _ev_count else "—"
            # Make leak name a hand-list popup link to candidate hands
            if _leak_cands:
                _leak_pool = [c.get('hand_id', '') for c in _leak_cands if c.get('hand_id')]
                _leak_sel = _popup_example_ids(_leak_pool, priority=1)  # P1: leak candidate hands
                _leak_hids = ','.join(_leak_sel)
                _leak_title = _popup_title_with_count(
                    f"{name} — candidate hands ({len(_leak_pool)})", len(_leak_pool))
                _leak_cell = (f'<a class="hand-list-trigger" href="#" '
                             f'data-hids="{_leak_hids}" '
                             f'data-list-title="{_leak_title}">'
                             f'{name}</a>')
            else:
                # No candidate hands found — still link to the detail section
                _leak_cell = f'[{name}](#{self_anchor})'
            doc.w(f"| {_xref(self_anchor, f'S3.{i}')} | {_leak_cell} | {metric_str} | "
                  f"{_ev_cell} | {status_tag} | {judg_short} | {_xref(anchor, label)} |")
        doc.w("")
        doc.w(f"<<REVIEWROW|section|sec-3|S3 Strategic Leaks>>")
        doc.w("")

        # Per-leak detail (analyst-judged only — candidates are in popup now).
        for i, leak in enumerate(promoted, 1):
            name = leak if isinstance(leak, str) else (
                   leak.get('name') or leak.get('leak') or str(leak))
            self_anchor = f"sec-3-{i}"
            doc.w(f"<<ANCHOR:{self_anchor}>>")
            doc.w(f"<<ANCHOR_COMPAT:sec-iii-2-{i}>>")
            cmt = leaks_commentary.get(name, {})
            judgment = cmt.get('judgment') or ''
            examples = cmt.get('examples') or []
            n_examples = len(examples) if examples else 0
            if not cmt:
                # Batch 3 (#5): show counterexamples even without analyst commentary
                _ce_cands = _candidate_hands_for_leak(name, hands, s)
                if len(_ce_cands) >= 3:
                    _hbi = s.get('_hands_by_id') or {}
                    # Partition by net_bb: worst = clean mistake, middle = boundary, best = counter
                    _ce_sorted = sorted(_ce_cands,
                                        key=lambda c: (_hbi.get(c.get('hand_id', ''), {}).get('net_bb', 0)))
                    _clean = _ce_sorted[0]
                    _boundary = _ce_sorted[len(_ce_sorted)//2]
                    _counter = _ce_sorted[-1]
                    doc.w(f"<details><summary><strong>S3.{i} {name}</strong> "
                          f"— flagged, {len(_ce_cands)} candidate hands</summary>")
                    doc.w("")
                    doc.w("| Type | Hand | Net BB | Context |")
                    doc.w("|---|---|---|---|")
                    for _lbl, _ce in [('Clean mistake', _clean), ('Boundary', _boundary),
                                      ('Counterexample', _counter)]:
                        _ce_h = _hbi.get(_ce.get('hand_id', ''))
                        _ce_ref = _hand_ref(_ce_h) if _ce_h else f"`{_ce.get('hand_id','?')[-8:]}`"
                        _ce_net = _ce_h.get('net_bb', 0) if _ce_h else 0
                        doc.w(f"| {_lbl} | {_ce_ref} | {_ce_net:+.1f} | {_ce.get('context', '')} |")
                    doc.w("")
                    doc.w(f"*Click the leak name in the table above for all {len(_ce_cands)} hands.*")
                    doc.w("</details>")
                    doc.w("")
                else:
                    doc.w(f"*S3.{i} {name} — flagged by metric. Click the leak name "
                          f"in the table above to see candidate hands.*")
                    doc.w("")
                continue
            has_real_content = bool(examples or (judgment and len(judgment) > 120))
            if not has_real_content:
                # Renderer link BUG-2: stub for thin-content leaks
                doc.w(f"*S3.{i} {name} — analyst noted but detail is thin.*")
                doc.w("")
                continue
            doc.w(f"<details><summary><strong>S3.{i} {name}</strong> "
                  f"— full reasoning + example hands ({n_examples})</summary>")
            doc.w("")
            if cmt.get('metric_summary'):
                doc.w(f"**Metric:** {cmt['metric_summary']}")
                doc.w("")
            if judgment:
                _emit_analyst_judgment(doc, judgment)
                doc.w("")
            # WIRING: Coaching decision tree for this leak
            try:
                from gem_coaching_trees import get_tree_for_leak_name
                _tree = get_tree_for_leak_name(name)
                if _tree:
                    doc.w(f"**Decision Tree: {_tree['title']}**")
                    doc.w("")
                    for _step in _tree['steps']:
                        doc.w(f"- {_step}")
                    doc.w("")
                    doc.w(f"*Memory rule: {_tree['memory_rule']}*")
                    doc.w("")
            except Exception:
                pass
            if examples:
                doc.w("**Example hands:**")
                doc.w("")
                doc.w("| Hand | Context | Verdict |")
                doc.w("|---|---|---|")
                for ex in examples[:8]:
                    # B133: tolerate either a dict {hand_id,context,verdict}
                    # or a bare hand-id string in __synthesis__ examples.
                    if isinstance(ex, str):
                        ex = {'hand_id': ex}
                    hid = ex.get('hand_id', '')
                    h = s['_hands_by_id'].get(hid)
                    # B133: register the example hand so XIV.B has an appendix
                    # entry for it — otherwise the III.2 link is dead when the
                    # hand was not separately analyst-reviewed.
                    if hid:
                        _state._record_citation_explicit(hid, 'sec-3',
                                                  'S3 Strategic Leak example')
                    ref = _hand_ref(h) if h else f"`{hid[-8:]}`"
                    doc.w(f"| {ref} | {ex.get('context','—')} | "
                          f"{_humanize_verdicts(ex.get('verdict','—'))} |")
                doc.w("")
            doc.w("</details>")
            doc.w("")

    # === Subsections gained from other sections ===
    # sec-13-1 Cleared / Population Deviations (from S13)
    _emit_sub_cleared_pop(doc, s, rd, hands)
    # sec-13-2 Read-Dependent Deviations (from S13)
    _emit_sub_read_dep(doc, s, rd, hands)
    # sec-13-3 Justified Variance (from S13)
    _emit_sub_justified(doc, s, rd, hands)
    # sec-4-1 Clinical Examples (from S4)
    _emit_sub_clinical(doc, s, rd, hands)
    # sec-4-2 Out-of-Bound Leak Discovery (from S4)
    _emit_sub_oob_discovery(doc, s, rd, hands)
    # sec-1-2 Top P&L Lines + Deep Runs (from S1)
    from gem_report_draft.sections_financial import _emit_sub_top_pnl_lines
    _emit_sub_top_pnl_lines(doc, s, rd, hands)
    # sec-5-6 Solver Confirmation Pass (from S5)
    from gem_report_draft.sections_iv_xii import _emit_sub_solver_confirm
    _emit_sub_solver_confirm(doc, s, rd, hands)


def _emit_iii_cleared_justified(doc, s, rd, hands):
    """S13 — Aggression Profile (restructured from Cleared/Justified)."""
    doc.section("sec-13", "S13. Aggression Profile",
                "AF breakdown, check-raises, drill clusters, sizing, bluff profile")

    # Import helpers from sections_iv_xii (no circular dependency)
    from gem_report_draft.sections_iv_xii import (
        _emit_sub_af_breakdown, _emit_sub_cr_frequency,
        _emit_sub_cr_made, _emit_sub_agg_drills,
        _emit_sub_ip_3bet_sizing, _emit_sub_bluff_all_streets)

    # Aggression subsections in user's requested order:
    _emit_sub_af_breakdown(doc, s, rd, hands)
    _emit_sub_cr_frequency(doc, s, rd, hands)
    _emit_sub_cr_made(doc, s, rd, hands)
    _emit_sub_agg_drills(doc, s, rd, hands)
    _emit_sub_ip_3bet_sizing(doc, s, rd, hands)
    _emit_sub_bluff_all_streets(doc, s, rd, hands)


def _emit_iii_clinical_picks(doc, s, rd, hands):
    """S4 — Tourney Type: PKO research teaching layer + bounty audit.

    v8.12.0 restructure (PKO Research Integration spec + review guardrails):
    S4.1 Snapshot · S4.2 BB Defense Teaching Spots · S4.3 Multiway Amplifier
    Matrix · S4.4 All-In / Bounty Capture Audit (+ migration audit + legacy
    HU detail) · S4.5 Out-of-Scope. All analytical facts come from
    rd['pko_research'] (built upstream); the renderer only displays.
    Fail-soft: when the research aggregation failed, S4.1-S4.3/S4.5 are
    omitted (S4.4 legacy detail still renders) and old discounts are NEVER
    restored. Aggregate-only items are Review/teaching only — they never
    enter Top Punts, BB/100 estimates, or confirmed-mistake counts.
    """
    from gem_report_draft._helpers import render_count_cell as _rcc
    doc.section("sec-4", "S4. Tourney Type",
                "bounty & PKO — research teaching layer + capture audit")

    pr = rd.get('pko_research') or {}
    _ok = bool(pr.get('enabled'))
    if not _ok:
        doc.w("*PKO research tables unavailable for this run (aggregation "
              "skipped — see build log). The bounty capture audit below "
              "still reflects the v8.12.0 live-logic rules.*")
        doc.w("")

    if _ok:
        # ---- S4.1 PKO Format Snapshot --------------------------------
        doc.subsection("sec-4-pko1", "S4.1 PKO Format Snapshot",
                       "routing dashboard — counts are clickable")
        doc.w("*Routing dashboard only — no strategic claims. Counts are "
              "clickable; 0 means none this session.*")
        doc.w("")
        snap = pr.get('snapshot', {})
        _rows = [
            ('Bounty-format hands', 'bounty_hands'),
            ('PKO-sensitive opps (BB defense)', 'pko_sensitive_opps'),
            ('Multiway PKO opps', 'multiway_opps'),
            ('All-in bounty opps', 'allin_bounty_opps'),
            ('Out-of-scope PKO spots', 'out_of_scope'),
            ('Needs exact GTOW grid', 'needs_exact_grid'),
        ]
        doc.w("| Metric | Value |")
        doc.w("|---|---|")
        for _lbl, _k in _rows:
            _ids = snap.get(_k, []) or []
            doc.w("| " + _lbl + " | "
                  + _rcc(len(_ids), _ids, 'PKO Snapshot → ' + _lbl) + " |")
        doc.w("")

        # ---- S4.2 PKO BB Defense Teaching Spots ----------------------
        doc.subsection("sec-4-pko2", "S4.2 PKO BB Defense Teaching Spots",
                       "GTOW ICMPKO-vs-Classic aggregate deltas")
        doc.w("*Bounty-format BB defense spots where GTOWizard PKO aggregates "
              "differ from Classic/ICM. Counts are clickable. **Missed** = "
              "Hero folded where the Classic chart says defend (chart-backed). "
              "**Wrong** (too wide) = Hero continued and the Classic detector "
              "says too loose. **Review** = aggregate PKO pressure marks a study spot — "
              "NOT a confirmed mistake. Deltas are quoted as ranges because "
              "they are stack-set dependent; small samples are drill cues, "
              "not frequency reads.*")
        doc.w("")
        _trows = pr.get('teaching_rows', []) or []
        if _trows:
            # v8.14.0 Slice E rev-2 (GPT Blocker 3): renamed Spot -> Opportunity
            # and split the old merged "Flagged" into explicit Wrong (continued
            # too loose) + Missed (folded a chart defend). Counts stay the
            # clickable control (no separate "Hands" column). Review kept — it is
            # the dominant PKO bucket and must keep its own clickable count.
            # v8.19.0 Chapter E (PHF-005): unambiguous headers so the reader can tell
            # Hero's behaviour from a confirmed Classic mistake from an ungraded PKO
            # candidate. Actual->Hero rate, Wrong->Too wide vs Classic, Missed->Missed
            # vs Classic, Review->PKO combo review (the _t() cell keys are unchanged).
            doc.w("| Opportunity | PKO Δ | Seen | Hero rate | Too wide vs Classic | "
                  "Missed vs Classic | PKO combo review | Drill cue |")
            doc.w("|---|---|---|---|---|---|---|---|")
            for _r in _trows:
                _rng = _r.get('delta_range_pp', [0, 0])
                _base = _r.get('classic_defend_pct')
                if _base:
                    _rl, _rh = (_rng[0] / _base * 100), (_rng[1] / _base * 100)
                    _dtxt = ("%+.0f%% to %+.0f%% rel" % (_rl, _rh)
                             if abs(_rl - _rh) >= 0.5 else "%+.0f%% rel" % _rh)
                    _dtxt += " (Classic %.0f%%)" % _base
                else:
                    _dtxt = ("%+.1f to %+.1fpp" % (_rng[0], _rng[1])
                             if _rng[0] != _rng[1] else "%+.1fpp" % _rng[0])
                if _r.get('confidence') == 'directional_aggregate':
                    _dtxt += " ⚠"
                _c = _r['cells']
                _spot_cell = ("%s — %s · %s · %s" % (
                    _r['spot'], _r['depth'], _r['players'], _r['coverage']))
                def _t(col, _c=_c, _r=_r):
                    return _rcc(len(_c[col]), _c[col],
                                "PKO BB Defense → " + _r['spot'] + " → "
                                + _r['depth'] + " → " + col)
                _cue = str(_r.get('drill_cue', ''))
                _mix = str(_r.get('action_mix', 'n/r'))
                if _mix and _mix != 'n/r':
                    _cue = (_cue + ' · ' if _cue else '') + _mix
                # Wrong = Too wide (continued too loose); Missed = folded a chart
                # defend; each count is its own clickable hand-list trigger.
                doc.w("| " + _spot_cell + " | " + _dtxt + " | "
                      + _t('Seen') + " | " + _t('Actual') + " | "
                      + _t('Too wide') + " | " + _t('Missed') + " | "
                      + _t('Review') + " | " + _cue + " |")
            doc.w("")
            doc.w("*Relative % is shown where the Classic defend baseline was "
                  "recorded (3 buckets); the remaining baselines are queued "
                  "for the B151 extraction micro-pass — those rows stay in "
                  "absolute pp.*")
            doc.w("")
            # v8.19.0 Chapter E (PHF-005): aggregate node research is NOT a hand-level
            # verdict. "Too wide / Missed vs Classic" are graded against the Classic
            # baseline; "PKO combo review" are ungraded candidates only.
            doc.w("*\"Too wide / Missed vs Classic\" are graded against the Classic "
                  "baseline. \"PKO combo review\" lists **ungraded** candidates — an "
                  "aggregate node looking under-defended does **not** prove any specific "
                  "bottom combo (e.g. 32o) should continue; that combo may still be a "
                  "correct fold.*")
            doc.w("")
        else:
            doc.w("*No PKO-sensitive BB defense spots this session.*")
            doc.w("")

        # ---- S4.3 PKO Multiway Amplifier Matrix ----------------------
        doc.subsection("sec-4-pko3", "S4.3 PKO Multiway Amplifier Matrix",
                       "player count × depth × coverage")
        doc.w("*Multiway PKO pressure can be much larger than heads-up bounty "
              "pressure, especially at short stacks. Grades use the FLOOR of "
              "the measured delta range (validation run 2026-06-11).*")
        doc.w("")
        _mw = [r for r in _trows if r['players'] in ('3-way', '4-way')]
        if _mw:
            doc.w("| Spot | Depth | Coverage | PKO Δ bucket | Seen | Missed | "
                  "Review |")
            doc.w("|---|---|---|---|---|---|---|")
            for _r in _mw:
                _c = _r['cells']
                def _t(col, _c=_c, _r=_r):
                    return _rcc(len(_c[col]), _c[col],
                                "PKO Multiway Matrix → " + _r['spot'] + " → "
                                + _r['depth'] + " → " + col)
                doc.w("| " + _r['spot'] + " | " + _r['depth'] + " | "
                      + _r['coverage'] + " | " + str(_r.get('delta_bucket', '?'))
                      + " | " + _t('Seen') + " | " + _t('Missed') + " | "
                      + _t('Review') + " |")
        else:
            doc.w("*No multiway PKO spots this session.*")
        doc.w("")

    # ---- S4.4 PKO All-In / Bounty Capture Audit ----------------------
    doc.subsection("sec-4-pko4", "S4.4 PKO All-In / Bounty Capture Audit",
                   "capture spots + v8.12.0 migration audit")
    doc.w("*This audit covers all-in bounty capture spots — separate from the "
          "BB-defense teaching layer. Multiway all-ins are NOT evaluated with "
          "the old HU flat-discount model (v8.12.0: no numeric discount for "
          "covered, mystery, or multiway spots).*")
    doc.w("")
    if _ok:
        _fams = pr.get('allin_families', {}) or {}
        _fam_rows = [
            ('HU bounty all-in calls', 'hu_calls'),
            ('HU bounty jams', 'hu_jams'),
            ('Multiway bounty all-ins', 'multiway'),
            ('Bounty not collectible (covered)', 'no_bounty'),
        ]
        doc.w("| Spot family | Seen |")
        doc.w("|---|---|")
        for _lbl, _k in _fam_rows:
            _ids = _fams.get(_k, []) or []
            doc.w("| " + _lbl + " | "
                  + _rcc(len(_ids), _ids, 'PKO All-In Audit → ' + _lbl) + " |")
        doc.w("")
        _mig = pr.get('migration_audit', []) or []
        if _mig:
            doc.w("**PKO Migration Audit** — old flat model vs v8.12.0 gated "
                  "model vs the v8.12.1 depth-scaled SHADOW model (not yet "
                  "authoritative). Every changed hand is listed; "
                  "math_changed_only rows changed required equity without "
                  "flipping the verdict.")
            doc.w("")
            doc.w("| Hand | Spot | Old req | New req | Shadow req | "
                  "Old verdict | New verdict | Impact | Reason |")
            doc.w("|---|---|---|---|---|---|---|---|---|")
            for _m in _mig[:30]:
                _cell = _rcc(1, [_m.get('id')],
                             'PKO Migration Audit → ' + str(_m.get('reason')))
                doc.w("| " + _cell + " | " + str(_m.get('spot', '')) + " | "
                      + str(_m.get('old_req', '')) + "% | "
                      + str(_m.get('new_req', '')) + "% | "
                      + str(_m.get('shadow_req', '')) + "% | "
                      + (str(_m.get('old_verdict')) or '—') + " | "
                      + (str(_m.get('new_verdict')) or '—') + " | "
                      + str(_m.get('impact_type', '')) + " | "
                      + str(_m.get('reason', '')) + " |")
            if len(_mig) > 30:
                doc.w("| … | " + str(len(_mig) - 30)
                      + " more rows in data | | | | | | | |")
            doc.w("")
        else:
            doc.w("*No HU all-in decision changed under the v8.12.0 PKO all-in "
                  "model. Multiway and BB-defense PKO spots are evaluated "
                  "separately.*")
            doc.w("")

    # Legacy HU all-in equity detail (information preserved; flat-discount
    # framing replaced by the audit above).
    from gem_report_draft.sections_iv_xii import _emit_sub_bounty_pko
    _emit_sub_bounty_pko(doc, s, rd, hands)

    if _ok:
        # ---- S4.5 Out-of-Scope PKO Spots ------------------------------
        doc.subsection("sec-4-pko5", "S4.5 Out-of-Scope PKO Spots",
                       "transparency — research backlog, not mistakes")
        doc.w("*These hands occurred in bounty formats but are outside the "
              "current extracted GTOWizard PKO research. Listed for "
              "transparency and future research — they are NOT classified as "
              "mistakes.*")
        doc.w("")
        _oos = pr.get('oos', {}) or {}
        _next = pr.get('oos_next_action', {}) or {}
        if _oos:
            doc.w("| Area | Count | Next action |")
            doc.w("|---|---|---|")
            _lbls = {
                'out_of_scope_mystery': 'Mystery bounty',
                'out_of_scope_pushfold': 'Sub-12bb push/fold',
                'out_of_scope_deep': 'Deep (>60bb)',
                'out_of_scope_5way': '5+ way pots',
                'out_of_scope_sb': 'SB defense',
                'out_of_scope_position': 'Non-blind positions',
                'out_of_scope_no_open': '3-bet pots / no single open',
                'review_band_edge': 'Depth band edge',
                'allin_family': 'All-in family (see S4.4)',
            }
            for _r, _ids in _oos.items():
                _lbl = _lbls.get(_r, _r)
                doc.w("| " + _lbl + " | "
                      + _rcc(len(_ids), _ids, 'PKO Out-of-Scope → ' + _lbl)
                      + " | " + str(_next.get(_r, 'Future research')) + " |")
        else:
            doc.w("*Nothing out of scope this session.*")
        doc.w("")


def _emit_section_iii(doc, s, rd, hands):
    """Section III wrapper — calls the four sub-emitters in original order."""
    _emit_iii_punts_mistakes(doc, s, rd, hands)
    _emit_iii_strategic_leaks(doc, s, rd, hands)
    _emit_iii_cleared_justified(doc, s, rd, hands)
    _emit_iii_clinical_picks(doc, s, rd, hands)


# ============================================================
# EXTRACTED SUBSECTION HELPERS
# ============================================================
# These functions were extracted from the original section emitters so they
# can be called independently from their new parent sections.  All
# _hand_ref() / _href() citation side-effects fire at the original
# relative point.
# ============================================================

def _emit_sub_exploits(doc, s, rd, hands):
    """S7.3 Exploits (Pool-Specific) — extracted from _emit_mental_game."""
    # II.5 Exploits (Pool-Specific) — Jasper-5
    doc.subsection("sec-7-3", "S7.3 Exploits (Pool-Specific) — Jasper-5",
                   "9 pool-exploit metrics — TENTATIVE targets, tracking-mode")
    doc.w("*Jasper-5 metrics target known online-pool mistakes. Targets are "
          "**tentative** until ≥5K hands of pool data accumulate. Per Quick "
          "Reference E2, Jasper sits OUTSIDE Dave > Amit > Jaka — these are "
          "pool exploits, not strategy axioms. Dave wins any conflict.*")
    doc.w("")
    core = s.get('core', {})
    csv = s.get('csv_row', {})

    # Phase 4.8: Groups A+B merged into one table with grouped Exploit column.
    # Group labels: "Float Flop / CR cbet" and "BB Iso vs SB Limp".
    _ex_hdr = "| Exploit | Metric | Status | Rate | Target | Delta | Sample | Notes |"
    _ex_sep = "|---|---|:---:|---:|---|---|---:|---|"
    _ex_rows = []

    # Float Flop / CR cbet rows
    fl_pct = core.get('call_cbet_ip_pct', 0)
    fl_n = core.get('call_cbet_ip_n', 0)
    fl_count = round(fl_pct * fl_n / 100) if fl_n else 0
    cr_pct = core.get('raise_cbet_oop_pct', 0)
    cr_n = core.get('raise_cbet_oop_n', 0)
    cr_count = round(cr_pct * cr_n / 100) if cr_n else 0
    _ex_first_float = True
    for label, x, n, tlo, thi, note in [
        ("Float Flop (Call CBet IP)", fl_count, fl_n, 35, 50,
         "J#5: float vs over-cbetters in position"),
        ("Raise CBet OOP (CR)", cr_count, cr_n, 8, 15,
         "J#4 OOP half"),
    ]:
        _grp = "**Float Flop / CR cbet**" if _ex_first_float else ""
        _ex_first_float = False
        if n == 0 or n is None:
            _ex_rows.append(
                f"| {_grp} | {label} | ⚪ | — | "
                f"{tlo}-{thi}% | — | — | {note} |")
        else:
            rate = 100.0 * x / n
            ci_lo, ci_hi = _wilson_ci(x, n)
            verdict = _verdict_ci(x, n, tlo, thi, n_min=10)
            ci_tip = f'<span class="ci-tip" title="CI 90%: {ci_lo:.0f}-{ci_hi:.0f}%">ⓘ</span>'
            delta = rate - (tlo + thi) / 2
            _ex_rows.append(
                f"| {_grp} | {label} | {verdict} | "
                f"{rate:.1f}% {ci_tip} | {tlo}-{thi}% | {delta:+.1f} pp | "
                f"n={n} | {note} |")

    # BB Iso vs SB Limp rows
    bb_iso_pct = core.get('bb_iso_sb_limp_pct', 0)
    bb_iso_n = core.get('bb_iso_sb_limp_n', 0)
    bb_iso_count = round(bb_iso_pct * bb_iso_n / 100) if bb_iso_n else 0
    if bb_iso_n == 0 or bb_iso_n is None:
        _ex_rows.append(
            "| **BB Iso vs SB Limp** | BB Iso vs SB Limp | ⚪ | — | "
            "65-85% | — | — | J#2: punish weak SB limp range |")
    else:
        rate = 100.0 * bb_iso_count / bb_iso_n
        ci_lo, ci_hi = _wilson_ci(bb_iso_count, bb_iso_n)
        verdict = _verdict_ci(bb_iso_count, bb_iso_n, 65, 85, n_min=10)
        ci_tip = f'<span class="ci-tip" title="CI 90%: {ci_lo:.0f}-{ci_hi:.0f}%">ⓘ</span>'
        delta = rate - 75.0
        _ex_rows.append(
            f"| **BB Iso vs SB Limp** | BB Iso vs SB Limp | {verdict} | "
            f"{rate:.1f}% {ci_tip} | 65-85% | {delta:+.1f} pp | "
            f"n={bb_iso_n} | J#2: punish weak SB limp range |")
    bb_check_pct = core.get('bb_check_sb_limp_pct', 0)
    if bb_iso_n > 0:
        bb_check_count = round(bb_check_pct * bb_iso_n / 100)
        _ex_rows.append(
            f"| | ↳ BB Check (took flop) | — | "
            f"{bb_check_pct:.1f}% ({bb_check_count}/{bb_iso_n}) | "
            f"15-35% (residual) | — | n={bb_iso_n} | "
            f"informational — rest of distribution |")

    _ex_blk = variance_ledger_block("t4-exploit-merged", _ex_hdr, _ex_sep, _ex_rows)
    doc.write_block(_ex_blk)
    doc.w("")

    # Fold-to-CBet by Sizing Bucket (Jasper #1 + #3)
    # Phase 4.8: status 2nd column, Folds/Opps second-to-last, street grouped
    doc.w("**Fold-to-CBet by Sizing Bucket:**")
    doc.w("")
    doc.w("| Street | Status | Bucket | Rate | Target | Folds/Opps | Notes |")
    doc.w("|---|:---:|---|---|---|---|---|")
    f_buckets = core.get('fold_to_cbet_by_size', {})
    for bucket, target_band, note in [
        ('small',  (0, 55),  "J#1: defend wider vs block bets"),
        ('medium', (45, 65), "merged middle-strength M20 zone"),
        ('large',  (55, 70), "polarized — pool more value-heavy"),
    ]:
        d = f_buckets.get(bucket, {})
        opps, folds, pct = d.get('opps', 0), d.get('folds', 0), d.get('pct', 0)
        if opps > 0:
            verdict = _verdict_ci(folds, opps, target_band[0], target_band[1], n_min=10)
            # Clickable fold/call count
            _fc_fids = d.get('fold_ids', [])
            _fc_cids = d.get('call_ids', [])
            if _fc_fids:
                _fc_sel = _popup_example_ids(_fc_fids, priority=1)  # P1: fold-to-cbet leak drill
                _fc_str = ','.join(_fc_sel)
                _fc_cell = (f'<a class="hand-list-trigger" href="#" '
                           f'data-hids="{_fc_str}" '
                           f'data-list-title="Folds to flop {bucket} c-bet ({folds})">'
                           f'{folds}/{opps}</a>')
            else:
                _fc_cell = f'{folds}/{opps}'
            doc.w(f"| Flop | {verdict} | {bucket} | {pct:.1f}% | "
                  f"{target_band[0]}-{target_band[1]}% | {_fc_cell} | {note} |")
    t_buckets = core.get('fold_to_turn_cbet_by_size', {})
    for bucket, target_band, note in [
        ('small',  (0, 50),  "J#3: call more vs block-bet turns"),
        ('medium', (45, 65), "merged middle"),
        ('large',  (55, 70), "J#3: fold more vs polarized turn"),
    ]:
        d = t_buckets.get(bucket, {})
        opps, folds, pct = d.get('opps', 0), d.get('folds', 0), d.get('pct', 0)
        if opps > 0:
            verdict = _verdict_ci(folds, opps, target_band[0], target_band[1], n_min=10)
            doc.w(f"| Turn | {verdict} | {bucket} | {pct:.1f}% | "
                  f"{target_band[0]}-{target_band[1]}% | {folds}/{opps} | {note} |")
    doc.w("")
    doc.w("*Tentative targets — leak deriver does NOT yet promote Jasper-5 metrics to "
          "Section III leaks. Tracking-mode only until calibrated against ≥5K hands "
          "of pool data.*")
    doc.w("")



def _emit_sub_cleared_pop(doc, s, rd, hands):
    """S13.1 Cleared / Population Deviations — extracted from _emit_iii_cleared_justified."""
    # III.3 Cleared / Misapplied Heuristics
    # B41 (v7.50, Ron 2026-05-17): renamed from "Misapplied Heuristics" to
    # "Cleared / Population Deviations" — the section serves two purposes:
    # (a) per-hand analyst-cleared verdicts (formerly mislabeled "misapplied"),
    # (b) population-level GTO deviation rules. Renaming makes the per-hand
    # meaning legible without losing the population-deviation content.
    doc.subsection("sec-13-1", "S13.1 Cleared / Population Deviations",
                   "analyst-cleared per-hand verdicts + aggregate GTO deviations")

    # B148 (v7.71, Ron 2026-05-23): per-hand analyst-cleared verdicts. The
    # section description has promised "analyst-cleared per-hand verdicts"
    # since B41, but the renderer only emitted the aggregate population-
    # deviation table — so a hand the analyst explicitly cleared (e.g. a P6
    # detector punt overturned to III.3) appeared in the III.1 "suppressed"
    # note but had no home in III.3 itself. List every III.3 verdict here;
    # the hand-ref links to the full analyst argument in the appendix.
    _analyst_iii3 = [(hid, cmt) for hid, cmt
                     in (rd.get('analyst_commentary', {}) or {}).items()
                     if isinstance(cmt, dict)
                     and cmt.get('verdict', '').startswith(('III.0', 'III.3'))]
    if _analyst_iii3:
        _hbid_iii3 = {h.get('id', ''): h for h in hands}
        # B173 (Ron 2026-05-24): the per-hand cleared verdicts are reviewed-
        # and-cleared QA content. Kept for traceability but collapsed by
        # default so the active population-deviation signal below leads — the
        # user shouldn't have to scroll past hands already cleared.
        doc.w(f"<details><summary><strong>▸ Per-hand analyst-cleared verdicts "
              f"({len(_analyst_iii3)})</strong> — hands reviewed and cleared, "
              f"including detector flags the analyst overturned. Expand to "
              f"inspect; full argument per hand is in the appendix.</summary>")
        doc.w("")
        _m3_hdr = "| Hand Reference | Cards | Cleared As | Verdict |"
        _m3_sep = "|---|---|---|---|"
        _m3_rows = []
        for hid, cmt in _analyst_iii3:
            h = _hbid_iii3.get(hid)
            href = _hand_ref(h) if h else f"`{hid[-8:]}`"
            cards = (_cards_str_to_pills(''.join(h.get('cards', [])))
                     if h else '—') or '—'
            spot = cmt.get('spot', '')
            type_label = ((spot.split('. ')[0][:80] if '. ' in spot
                           else spot[:80]) if spot else '—')
            # B161 (Ron 2026-05-24): apply the III.3 outcome sub-label so a
            # hand carrying outcome=spew_called/suckout/lost_flip/top_of_range
            # renders its real emoji + word (🤡 Spew-called, 🤢 Suckout, …)
            # instead of a blanket "👍 III.3 Cleared".
            # Item 1: III.0 hands show ⚖️ GTO-Standard instead of 👍 Cleared.
            _vcls = (cmt.get('verdict', '') or '').split()[0]
            if _vcls == 'III.0':
                _oce, _oct = _outcome_label(cmt, default=('⚖️', 'GTO-Standard'))
                _oct_disp = (_oct[:1].upper() + _oct[1:]) if _oct else 'GTO-Standard'
                # v8.12.9 policy: no Roman codes user-facing
                _m3_rows.append(f"| {href} | {cards} | {type_label} | "
                      f"{_oce} {_oct_disp} |")
            else:
                _oce, _oct = _outcome_label(cmt)
                _oct_disp = (_oct[:1].upper() + _oct[1:]) if _oct else 'Cleared'
                _m3_rows.append(f"| {href} | {cards} | {type_label} | "
                      f"{_oce} {_oct_disp} |")
        # <details> boundary: block is INSIDE the <details>; open/close tags
        # are prose OUTSIDE. Do NOT move <details> into the block.
        _m3_blk = hand_evidence_table_block("iii3-cleared", _m3_hdr, _m3_sep, _m3_rows)
        doc.write_block(_m3_blk)
        doc.w("")
        doc.w("</details>")
        doc.w("")
    pf_devs = s.get('postflop_deviations_v732', [])
    if pf_devs:
        # v7.38: per Ron's request, surface example hand references for every
        # flagged metric. Detector records don't carry hand_ids, so we filter
        # the hands list at render-time by detector rule + position + behavior.
        hands_by_id = {h.get('id'): h for h in hands}
        def _examples_for(rule, pos, max_n=3):
            """Return up to max_n hand records matching a detector rule + position."""
            matches = []
            for h in hands:
                if h.get('position') != pos:
                    continue
                # Map detector rule name → filter predicate
                if rule == 'detector_fold_to_cbet_by_pos':
                    if (h.get('faced_villain_cbet_flop') and
                        h.get('fold_to_villain_cbet_flop') and
                        not h.get('first_in')):
                        matches.append(h)
                elif rule == 'detector_call_cbet_by_pos':
                    if (h.get('faced_villain_cbet_flop') and
                        h.get('called_villain_cbet_flop')):
                        matches.append(h)
                elif rule == 'detector_river_cbet_by_pos':
                    # Hero PFR'd, then fired/skipped a river bet
                    if h.get('pfr') and h.get('cbet_river_then_sd'):
                        matches.append(h)
                elif rule == 'detector_rfi_by_pos':
                    # Wide opens at this position
                    if h.get('first_in') and h.get('pfr'):
                        matches.append(h)
                # else: rule not yet mapped — skip
                if len(matches) >= max_n: break
            return matches

        # Item 6: analyst judgments + Est. BB/100 for each flagged deviation.
        # Judgments keyed by "Rule_label Position" in __synthesis__.leaks[...]
        # (same store as S3 leaks — unified analyst coverage gate).
        _synth = (rd.get('analyst_commentary', {}) or {}).get('__synthesis__', {})
        _dev_judgments = (_synth.get('leaks', {}) if isinstance(_synth, dict)
                         else {})
        _total_session_hands = (s.get('volume', {}).get('hands', 0)
                                or len(hands) or 1)

        doc.w('<span data-tip="Example-hand IDs are illustrative instances of '
              'the aggregate pattern — click any ID to jump to the full hand '
              'detail in the appendix.">*Aggregate per-position deviations '
              '(population-level, not per-hand):*</span>')
        doc.w("")
        doc.w("| Rule | Position | Rate | n | Target | Δ | Est. BB/100 "
              "| Judgment | Confidence | Hands |")
        doc.w("|---|---|---|---|---|---|---|---|---|---|")
        # B104 (Ron 2026-05-19): plain-text rule labels — detector codes
        # (detector_fold_to_cbet_by_pos) were unreadable. Map to natural text.
        _RULE_LABELS = {
            'detector_fold_to_cbet_by_pos': 'Fold to cbet',
            'detector_call_cbet_by_pos':    'Call cbet',
            'detector_turn_cbet_by_pos':    'Turn cbet',
            'detector_river_cbet_by_pos':   'River cbet',
            'detector_rfi_by_pos':          'Open (RFI)',
            'detector_3bet_by_pos':         '3-bet',
            'detector_fold_to_3bet_by_pos': 'Fold to 3-bet',
            'detector_squeeze_by_pos':      'Squeeze',
            'detector_donk_by_pos':         'Donk',
            'detector_xr_by_pos':           'Check-raise',
            'detector_probe_by_pos':        'Probe turn',
            'detector_float_by_pos':        'Float flop',
            'detector_delayed_cbet_by_pos': 'Delayed cbet',
        }
        _n_pending = 0
        for d in pf_devs[:15]:
            rule = d.get('rule','—'); pos = d.get('pos','—')
            rule_label = _RULE_LABELS.get(rule, rule)
            examples = _examples_for(rule, pos, max_n=5)
            ex_refs = []
            for h in examples:
                cards = _cards_str_to_pills(''.join(h.get('cards', [])))
                ref = _href(h, s['_hands_by_id'])
                ex_refs.append(f"{ref.split(' • ')[0]} {cards}")
            ex_str = ' • '.join(ex_refs) if ex_refs else '—'
            # Est. BB/100: sum of net_bb from matching hands / session hands * 100
            _leak_bb = sum(h.get('net_bb', 0) for h in examples)
            _est_bb100 = ((_leak_bb / _total_session_hands) * 100
                          if _total_session_hands else 0)
            _bb_cell = f"{_est_bb100:+.2f}" if examples else '—'
            # Analyst judgment from __synthesis__.leaks[key]
            _dev_key = f"{rule_label} {pos}"
            _jcmt = _dev_judgments.get(_dev_key, {})
            if isinstance(_jcmt, dict):
                _jtext = _jcmt.get('judgment', '') or ''
                _jstatus = (_jcmt.get('real_or_noise', '') or '').lower()
            else:
                _jtext = str(_jcmt) if _jcmt else ''
                _jstatus = ''
            _jtag = {'real': '🔴', 'mixed': '🟡',
                     'noise': '🟢', 'noise/justified': '🟢'}.get(
                _jstatus, '⚪')
            _jcell = f"{_jtag} {_jtext.split(chr(10))[0][:80]}" if _jtext else f"{_jtag} —"
            if _jstatus == '' or _jstatus not in ('real', 'mixed', 'noise', 'noise/justified'):
                _n_pending += 1
            doc.w(f"| {rule_label} | {pos} | "
                  f"{d.get('pct',0):.1f}% | {d.get('n',0)} | "
                  f"{d.get('target','—')}% | {d.get('delta_pp',0):+.1f}pp | "
                  f"{_bb_cell} | {_jcell} | "
                  f"{d.get('confidence','—')} | {ex_str} |")
        doc.w("")
        if _n_pending and pf_devs:
            doc.w(f"⚪ **{_n_pending} deviation"
                  f"{'s' if _n_pending > 1 else ''} not yet reviewed** "
                  f"— flagged by metrics, await analyst confirmation.")
            doc.w("")
    else:
        doc.w("⚪ No aggregate population deviations flagged this session.")
        doc.w("")


def _emit_sub_read_dep(doc, s, rd, hands):
    """S13.2 Read-Dependent Deviations — extracted from _emit_iii_cleared_justified."""
    # III.4 Read-Dependent Deviations
    # B77 (v7.56, Ron 2026-05-18): dedup — full hand details live in the
    # appendix (XIV.A) only. This section now lists each III.4 hand as a
    # one-line link + spot/axis summary. No duplicate prose.
    doc.subsection("sec-13-2", "S13.2 Read-Dependent Deviations",
                   "leak bucket — solver-quantified at the population baseline")
    analyst = rd.get('analyst_commentary', {}) or {}
    rd_quant = rd.get('read_dependent_quant', {}) or {}
    iii4_entries = []
    hands_by_id = {h.get('id'): h for h in hands}
    for hid, cmt in analyst.items():
        if isinstance(cmt, dict) and cmt.get('verdict', '').startswith('III.4'):
            iii4_entries.append((hid, cmt))
    if not iii4_entries:
        doc.w("⚪ No hands re-classified to read-dependent this session "
              "(analyst step produced no read-dependent verdicts).")
        doc.w("")
    else:
        doc.w("Hands flagged as exploitative-but-reasoned by analyst pass — "
              "*full grid + commentary in appendix*. **Pop baseline** is the "
              "river call/fold solver's population-baseline verdict (under-"
              "bluff factor 0.50); for calls it grades -EV, the bracket is "
              "the chip-EV given up vs folding — the leak cost of the decision, "
              "not the hand's net result:")
        doc.w("")
        doc.w("| Hand | Cards | Net BB | Pop baseline | Spot | Axis |")
        doc.w("|---|---|---:|---|---|---|")
        _q_leak = 0.0
        _q_nleak = 0
        _q_nsolv = 0
        for hid, cmt in iii4_entries:
            h = hands_by_id.get(hid)
            spot = (cmt.get('spot') or '—')
            # Trim spot to one line — short enough for a table cell
            if len(spot) > 80:
                spot = spot[:78] + '…'
            axis = cmt.get('decision_axis', '') or '—'
            ref = _hand_ref(h) if h else f"`{hid[-8:]}` (not in set)"
            cards_str = _cards_str_to_pills(''.join((h.get('cards') if h else []) or [])) or '—'
            net_bb = (h.get('net_bb') if h else 0) or 0
            _q = rd_quant.get(hid)
            if _q and _q.get('solvable'):
                _q_nsolv += 1
                _vp = _q.get('verdict_pop', 'CALL')
                _pev = _q.get('ev_call_pop_bb', 0.0)
                if _vp == 'FOLD':
                    pop_cell = f"🔴 **FOLD** ({_pev:+.1f})"
                    _q_leak += _pev
                    _q_nleak += 1
                elif _vp == 'INDIFF':
                    pop_cell = "🟡 ~indiff"
                else:
                    pop_cell = "🟢 CALL ✓"
            else:
                # P2b: label by actual decision street instead of misleading
                # "not solved" (the solver only prices river bluff-catches).
                if h and h.get('pf_allin'):
                    pop_cell = "*preflop all-in — n/a*"
                elif h and h.get('pf_settled'):
                    pop_cell = "*preflop settled — n/a*"
                elif h and len(h.get('board') or []) < 5:
                    _dec_st = {3: 'flop', 4: 'turn'}.get(
                        len(h.get('board') or []), 'pre-river')
                    pop_cell = f"*{_dec_st} commit — n/a*"
                else:
                    pop_cell = "*not solved*"
            doc.w(f"| {ref} | {cards_str} | {net_bb:+.1f} | {pop_cell} "
                  f"| {spot} | {axis} |")
        doc.w("")
        if _q_nsolv:
            doc.w(f"*Bucket leak (river-solvable calls): "
                  f"{_q_leak:+.1f} BB — {_q_nleak} of {_q_nsolv} priced "
                  f"call{'s' if _q_nsolv != 1 else ''} -EV vs the pool. "
                  f"\"CALL ✓\" = the read holds even vs the population; "
                  f"\"n/a\" = the key decision was preflop or on an earlier "
                  f"street, not a river bluff-catch the pool solver prices. "
                  f"Solver villain ranges are heuristic — the per-hand "
                  f"argument below is the authority on each read.*")
            doc.w("")

    # v7.60: Result-INDEPENDENT screener output. Lists HU river bluff-catch
    # calls whose CALL/FOLD verdict is not robust across the population
    # under-bluff band — surfaced for the analyst step regardless of whether
    # the call won or lost. Won read-dependent calls are the ones that never
    # reach the loss-anchored feed and silently reinforce a -EV habit.
    rd_screen = rd.get('read_dependent_screen', []) or []
    if rd_screen:
        n_won = sum(1 for c in rd_screen
                    if (c.get('read_dependent_screen') or {}).get('won'))
        # B187 (Ron 2026-05-25): reflect analyst-review status — the screener
        # is a diagnostic, but once the analyst has graded a surfaced hand it
        # must read as reviewed, not as a standing "pending analyst" item.
        _ascreen = rd.get('analyst_commentary', {}) or {}
        n_rev = sum(1 for c in rd_screen
                    if isinstance(_ascreen.get(c.get('id')), dict)
                    and _ascreen.get(c.get('id'), {}).get('verdict'))
        n_await = len(rd_screen) - n_rev
        review_state = ("all carry an analyst verdict (Analyst column)"
                        if n_await == 0 else
                        f"{n_rev} reviewed, {n_await} pending review")
        doc.w(f"**Result-independent screener** — {len(rd_screen)} HU river "
              f"call{'s' if len(rd_screen) != 1 else ''} where the verdict "
              f"flips between a GTO-balanced range and a population "
              f"under-bluffed range ({n_won} won / {len(rd_screen)-n_won} lost) "
              f"— {review_state}. Grade on population-baseline EV, not the "
              f"result:")
        doc.w("")
        doc.w("| Hand | Cards | Result | Sizing | GTO verdict | Flip | "
              "Analyst | Axis |")
        doc.w("|---|---|---:|---:|---|---|---|---|")
        for c in rd_screen:
            sc = c.get('read_dependent_screen') or {}
            hid = c.get('id', '')
            h = hands_by_id.get(hid)
            ref = _hand_ref(h) if h else f"`{hid[-8:]}`"
            cards_str = _cards_str_to_pills(
                ''.join((h.get('cards') if h else []) or [])) or '—'
            net = sc.get('result_net_bb', 0)
            res = (f"🟢 +{net:.1f}" if sc.get('won') else f"🔴 {net:.1f}")
            sizing = f"{sc.get('sizing_pct', 0):.0f}%"
            v_gto = sc.get('verdict_gto', '—')
            sev = sc.get('flip_severity', '—')
            _acmt = _ascreen.get(hid) if isinstance(_ascreen.get(hid), dict) else None
            v_analyst = (_verdict_display_label(_acmt.get('verdict')) or '📊 screened') if _acmt else '📊 screened'
            axis = sc.get('decision_axis', '—')
            if len(axis) > 90:
                axis = axis[:88] + '…'
            doc.w(f"| {ref} | {cards_str} | {res} | {sizing} | {v_gto} "
                  f"| {sev} | {v_analyst} | {axis} |")
        doc.w("")
        doc.w("*Screener is result-independent by construction: it tests "
              "whether the decision's EV sign survives the population read, "
              "not whether the river fell kindly. Analyst assigns the III.x "
              "verdict per hand.*")
        doc.w("")


def _emit_sub_justified(doc, s, rd, hands):
    """S13.3 Justified Variance — extracted from _emit_iii_cleared_justified."""
    # III.5 Justified Variance
    doc.subsection("sec-13-3", "S13.3 Justified Variance",
                   "correct decisions, bad outcomes")
    doc.w("Hands not classified as a cooler or a strategic leak default here. "
          "Bust hands with 1-2-action-back analysis showing correct line:")
    doc.w("")
    doc.w("*See I.3 Large-Loss Audit for the full list with verdicts.*")
    doc.w("")


def _emit_sub_clinical(doc, s, rd, hands):
    """S4.1 Clinical Examples — extracted from _emit_iii_clinical_picks."""
    # III.6 Clinical Examples
    # Item 7: renamed per Ron's review
    doc.subsection("sec-4-1", "S4.1 Mistakes to Go Over",
                   "high-leverage hands worth solver review")
    clinicals = rd.get('clinical_candidates', [])
    # Phase 4.8: Bug B17 caveat → tooltip on header instead of visible text
    ms_count = sum(1 for c in (clinicals or []) if 'Missed Steal' in c.get('reason',''))
    if ms_count:
        doc.w(f'<span data-tip="Chart calibration caveat (Bug B17): '
              f'{ms_count} of these are Missed Steal flags. The detector uses '
              f'a single hardcoded chart per position (BTN/CO/SB CORE+EXTENDED) '
              f'and does NOT vary by table_size. Hands like T8o or J7s at CO '
              f'49BB may flag CLEAR under a 6-max-style chart but be legitimate '
              f'folds at an 8-max table. Review each missed-steal flag against '
              f'the actual table size before promoting to a Dave-shortlist or '
              f'solver session.">⚠️ {ms_count} missed-steal flags — '
              f'hover for B17 caveat</span>')
        doc.w("")
    if clinicals:
        _m4_hdr = "| # | Hand Reference | Cards | Reason | Question |"
        _m4_sep = "|---|---|---|---|---|"
        _m4_rows = []
        for i, c in enumerate(clinicals[:10], 1):
            cards = c.get('cards', '—')
            if isinstance(cards, list):
                cards = ''.join(cards)
            cards = _cards_str_to_pills(cards)
            # Strip redundant "Mistake: " prefix — the table title makes it clear
            _reason = (c.get('reason') or '—')
            for _prefix in ('Mistake: ', 'Deviation: ', 'Punt: '):
                if _reason.startswith(_prefix):
                    _reason = _reason[len(_prefix):]
                    break
            # Scrub internal tokens from question text (fold_preflop etc.)
            _q = (c.get('question', 'line check') or 'line check')
            for _old, _new in (('fold_preflop', 'preflop fold'),
                               ('folded_preflop', 'preflop fold'),
                               ('check_fold', 'check-fold'),
                               ('check_call', 'check-call'),
                               ('check_raise', 'check-raise')):
                _q = _q.replace(_old, _new)
            _m4_rows.append(f"| {i} | {_hand_ref(c)} | {cards} | "
                  f"{_reason} | {_q} |")
        _m4_blk = hand_evidence_table_block("iii7-clinicals", _m4_hdr, _m4_sep, _m4_rows)
        doc.write_block(_m4_blk)
        doc.w("")
    else:
        doc.w("⚪ No clinical examples flagged this session.")
    doc.w("")


def _emit_sub_oob_discovery(doc, s, rd, hands):
    """S4.2 Out-of-Bound Leak Discovery — extracted from _emit_iii_clinical_picks."""
    # III.7 Out-of-Bound Leak Discovery
    doc.subsection("sec-4-2", "S4.2 Out-of-Bound Leak Discovery",
                   "deviation buckets as % of opportunities")
    ds = s.get('deviation_summary', {})
    rows = [(k, v) for k, v in ds.items() if isinstance(v, dict) and v.get('count', 0) > 0]
    if rows:
        positions = s.get('positions', {})
        n_fi_total = sum(p.get('fi', 0) for p in positions.values())
        n_bb_steal = s.get('facing_action', {}).get('bb_defense_vs_steal', {}).get('opps', 0)
        n_bb_nonsteal = s.get('facing_action', {}).get('bb_defense_vs_nonsteal', {}).get('opps', 0)
        # Denominator + acceptable-rate-band per bucket type
        # (rate = deviations / opps; small % is acceptable, high % = leak)
        bucket_meta = {
            'Wide Open':                    (n_fi_total, "FI opps",            (0, 4)),
            'Missed Open':                  (n_fi_total, "FI opps",            (0, 4)),
            'Missed BB Defend':             (n_bb_steal+n_bb_nonsteal, "BB-faced-raise opps", (0, 5)),
            'Wide BB Defend':               (n_bb_steal+n_bb_nonsteal, "BB-faced-raise opps", (0, 5)),
            'Missed Defend/3-Bet':          (None, "facing-raise opps",        (0, 5)),
            'Missed Rejam':                 (None, "<15BB facing-raise opps", (0, 5)),
            'Wide Defend/3-Bet':            (None, "facing-raise opps",        (0, 5)),
            'Wide BvB Iso (vs limp)':       (None, "BB-iso-vs-SB-limp opps",  (0, 8)),
        }
        # B164 (Ron 2026-05-24) + B190 (Ron 2026-05-25): every bucket label
        # links to where its hands are detailed. Buckets with a dedicated XIII
        # section point there; the rest get an inline evidence block emitted
        # right below the table (anchor sec-iii-7-ev-<slug>) so no bucket is a
        # dead label. XIII.1/2/3 + XIII.4-confirmed carry matching back-links.
        # B241 (Ron review 2026-05-26): the two CVJ buckets both pointed at
        # sec-xiii-4-confirmed — a shared dead-end with no CVJ hand examples.
        # Dropped from bucket_anchor so each falls through to its OWN inline
        # evidence block (distinct sec-iii-7-ev-<slug> anchors) listing the
        # actual flagged hands.
        bucket_anchor = {
            'Wide Open':                          'sec-xiii-1',
            'Missed Open':                        'sec-xiii-3',
            'Wide BB Defend':                     'sec-xiii-2',
        }
        import re as _re_iii7
        def _ev_slug(name):
            return 'sec-4-2-ev-' + _re_iii7.sub(r'[^a-z0-9]+', '-',
                                                  name.lower()).strip('-')
        dev_ev = rd.get('deviation_evidence', {}) or {}
        # Buckets with no XIII section but with evidence hands → inline anchor.
        inline_ev_buckets = [k for k, v in rows
                             if k not in bucket_anchor and dev_ev.get(k)]
        hdr = "| Status | Bucket | Rate | Acceptable | Common Hands | Count/Denom |"
        sep = "|---|---|---|---|---|---|"
        tbl_rows = []
        for k, v in rows:
            denom, denom_label, target = bucket_meta.get(k, (None, "—", (0, 5)))
            count = v.get('count', 0)
            common_str = ", ".join(str(x) for x in v.get('hands', [])[:6])
            _kanchor = bucket_anchor.get(k)
            if _kanchor:
                k_cell = f"[{k}](#{_kanchor})"
            else:
                # Renderer link BUG-3: Phase 4.8 v3 removed the inline
                # sec-4-2-ev-<slug> evidence blocks. Do NOT link to them.
                k_cell = k
            if denom and denom > 0:
                rate = 100.0 * count / denom
                ci_lo, ci_hi = _wilson_ci(count, denom)
                verdict = _verdict_ci(count, denom, target[0], target[1], n_min=10)
                tbl_rows.append(f"| {verdict} | {k_cell} | "
                      f"{rate:.1f}% | {target[0]}-{target[1]}% | {common_str} | "
                      f"{count}/{denom} ({denom_label}) |")
            else:
                tbl_rows.append(f"| ⚪ | {k_cell} | "
                      f"— | {target[0]}-{target[1]}% | {common_str} | "
                      f"{count}/— ({denom_label}) |")
        blk = leak_bucket_overview_block("iii7-buckets", hdr, sep, tbl_rows)
        doc.write_block(blk)
        doc.w("")
        doc.w("*Acceptable bands reflect that EVERY player's chart deviates a small "
              "% of the time — only sustained high deviation rates are leaks. "
              "🟢 = within target, 🟡 = borderline, 🔴 = >1 band-width over.*")
        doc.w("")
        # Phase 4.8 v3: removed inline <details> evidence blocks per user review.
        # Bucket evidence now only via XIII sections (linked from bucket names).
    else:
        doc.w("👍 All buckets within expected bands.")
        doc.w("")


def _emit_sub_picks(doc, s, rd, hands):
    """S4.3 Pokerbot's Picks — extracted from _emit_iii_clinical_picks."""
    # III.8 Pokerbot's Picks (B151, Ron 2026-05-23; algorithm B191, 2026-05-25).
    # Result-agnostic celebration of DECISION quality. v1 awarded a Pick ONLY
    # on an analyst archetype verdict — so a 145-candidate screen produced 0
    # Picks and an empty section (Ron: "145 candidates and nothing to write
    # back on? you need a change of algorithm"). B191: the pipeline now ranks
    # the structural candidates by signal strength and auto-promotes the
    # strongest as PROVISIONAL Picks (🔶) with an inferred archetype. An
    # analyst III.8 verdict still produces a CONFIRMED Pick (⭐) and overrides
    # the provisional inference. The section is never empty when strong
    # candidates exist.
    _ARCHETYPE_EMOJI = {
        'sick call':              '🎯',
        'sick fold':              '🛡️',
        'great value extraction': '💰',
        'great bluff':            '🃏',
        'trap-door play':         '🪤',
        'macro/icm leverage':     '⚖️',
        'macro / icm leverage':   '⚖️',
        'macro-icm leverage':     '⚖️',
    }
    analyst_all = rd.get('analyst_commentary', {}) or {}
    analyst_picks = [(hid, cmt) for hid, cmt in analyst_all.items()
                     if isinstance(cmt, dict)
                     and (cmt.get('verdict', '') or '').startswith('III.8')]
    _analyst_pick_ids = {hid for hid, _ in analyst_picks}

    # B191 ranking layer: weight each structural reason by signal strength and
    # infer a provisional archetype from the dominant (highest-weight) reason.
    # (reason-substring → (weight, archetype))
    _REASON_RULES = [
        ('laydown facing turn/river', 3, 'sick fold'),
        ('triple-barrel',             3, 'great bluff'),
        ('ICM-leverage phase',        3, 'macro/icm leverage'),
        ('check-raise',               2, 'trap-door play'),
        ('river bet/raise',           2, 'great value extraction'),
        ('premium hand in',           2, 'sick call'),
        ('double-barrel',             1, 'great bluff'),
        ('preflop squeeze',           1, 'trap-door play'),
        ('called a 3-bet/4-bet',      1, 'sick call'),
        ('large contested pot',       1, 'sick call'),
    ]
    def _score_candidate(cand, hand):
        reasons = (cand.get('bestplay_screen', {}) or {}).get('reasons', []) or []
        score = 0
        best_w, archetype = -1, None
        for r in reasons:
            rl = str(r).lower()
            for sub, w, arch in _REASON_RULES:
                if sub in rl:
                    score += w
                    if w > best_w:
                        best_w, archetype = w, arch
                    break
        # river/triple-barrel: SD reached → value, no SD → bluff (line shape,
        # not a result claim — a bluff is a bluff whether or not it got there).
        if archetype in ('great bluff', 'great value extraction') and hand:
            archetype = ('great value extraction' if hand.get('went_to_sd')
                         else 'great bluff')
        return score, archetype, reasons

    _bp_cands = rd.get('bestplay_screen', []) or []
    # B191 fix (Ron 2026-05-25): a hand the analyst flagged as a leak/punt
    # (III.1 / III.2) must NEVER be auto-promoted to a Pick — that is the
    # opposite of a well-played hand. Caught on 95737149 (the 99 river-jam
    # punt) being promoted as "great value extraction".
    # B249 fix (Ron 2026-05-27): the exclusion was too narrow. A hand the
    # analyst has ALREADY adjudicated with ANY verdict (I.7 cooler, III.3
    # cleared, III.4 read-dep, III.5 justified — not just III.1/III.2) is
    # by definition *reviewed*; it must never re-surface as "⚠️ awaiting
    # analyst review". Likewise a pipeline-detected cooler is a known
    # structural loss, not an open Pick candidate. Broaden the exclusion
    # set to every adjudicated hand so the provisional list only ever
    # holds genuinely un-reviewed hands.
    _adjudicated_ids = {hid for hid, cmt in analyst_all.items()
                        if isinstance(cmt, dict) and str(hid).startswith('TM')
                        and (cmt.get('verdict', '') or '').strip()}
    _adjudicated_ids |= {c.get('id') for c in
                         (s.get('coolers', {}) or {}).get('hands', [])
                         if isinstance(c, dict) and c.get('id')}
    _scored = []
    for c in _bp_cands:
        if not isinstance(c, dict) or not c.get('id'):
            continue
        if c['id'] in _analyst_pick_ids or c['id'] in _adjudicated_ids:
            continue
        # B212 (Ron review 2026-05-25): a hand that ended preflop has no
        # postflop play to showcase — promoting it to a Pick produced the
        # "where's the hand?!" empty-grid complaints (96413597, a 4-bet pot
        # that took it down preflop). A Pick must have a board.
        if not (c.get('board') or []):
            continue
        h = (s.get('_hands_by_id', {}) or {}).get(c['id'], {})
        sc, arch, reasons = _score_candidate(c, h)
        _scored.append((sc, c['id'], arch, reasons, c))
    _scored.sort(key=lambda x: -x[0])
    # Promote: score >= 4 (two strong markers, or one strong + supporting),
    # capped at 8 so the section stays a curated highlight, not a dump.
    _PROMOTE_MIN, _PROMOTE_CAP = 4, 8
    provisional = [(hid, arch, reasons, sc) for sc, hid, arch, reasons, c
                   in _scored if sc >= _PROMOTE_MIN][:_PROMOTE_CAP]
    _provisional_ids = {hid for hid, _, _, _ in provisional}

    n_picks_total = len(analyst_picks) + len(provisional)
    doc.subsection("sec-4-3", "S4.3 Pokerbot's Picks",
                   f"{len(analyst_picks)} analyst-confirmed "
                   f"{'pick' if len(analyst_picks) == 1 else 'picks'}"
                   + (f" · {len(provisional)} unelevated screening "
                      f"candidate{'s' if len(provisional) != 1 else ''}"
                      if provisional else ''))
    if not n_picks_total:
        # v8.12.4 (QA item 24): distinguish "no candidates" from "the analyst
        # adjudicated every candidate without awarding a single III.8". The
        # second is a checklist §9 violation (curate 5-10 Picks) and must be
        # visible, not an innocuous empty section.
        _n_bp_adjudicated = sum(1 for c in _bp_cands
                                if isinstance(c, dict)
                                and c.get('id') in _adjudicated_ids)
        if _n_bp_adjudicated >= 20:
            doc.w(f"⚠️ **0 Picks from {_n_bp_adjudicated} adjudicated "
                  f"screening candidates.** Every bestplay candidate received "
                  f"a verdict but none was graded a Pick — with this many "
                  f"candidates, checklist §9 expects 5-10 curated Picks. "
                  f"This usually means the candidates were batch-closed; "
                  f"re-review the strongest screening hands for genuine "
                  f"highlights.")
        else:
            doc.w("⚪ No Picks this session — no analyst archetype verdict and no "
                  "structural candidate scored above the screening threshold.")
        doc.w("")
    else:
        # B212 (Ron review 2026-05-25): the auto-promoted "provisional picks"
        # carried an INFERRED archetype ("sick call", "great bluff") that was
        # routinely wrong — KK/AKs in a 4-bet pot is not a "sick call", TPTK is
        # not a "great bluff" — and no real explanation of why the hand was
        # well played. A Pick is, by definition, a hand the analyst judged.
        # So: only analyst-confirmed picks are shown as Picks (with their real
        # commentary); the structural screen output is shown SEPARATELY as a
        # plain "candidates awaiting review" list — facts only, no fabricated
        # archetype, no fabricated "why it's a pick".
        if analyst_picks:
            doc.w("*A Pick recognises decision quality, not the result — "
                  "outcomes are ignored by design. Each links to its appendix "
                  "detail.*")
            doc.w("")
            _m5_hdr = "| # | Hand Reference | Cards | Archetype | Why It's a Pick |"
            _m5_sep = "|---|---|---|---|---|"
            _m5_rows = []
            _row_i = 0
            for hid, cmt in analyst_picks:
                _row_i += 1
                h = (s.get('_hands_by_id', {}) or {}).get(hid, {})
                cards = ''.join(h.get('cards', [])) if h else cmt.get('cards', '—')
                arche = (cmt.get('archetype', '') or '').strip()
                ae = _ARCHETYPE_EMOJI.get(arche.lower(), '⭐')
                arche_disp = f"{ae} {arche}" if arche else f"{ae} —"
                hook = (cmt.get('argument', '') or '').strip()
                if hook.startswith('**TL;DR:**'):
                    hook = hook[len('**TL;DR:**'):].strip()
                hook = hook.split('\n')[0].split('. ')[0].strip()
                if len(hook) > 110:
                    hook = hook[:107] + '…'
                ref = _href(h, s['_hands_by_id']) if h else f"`{hid[-8:]}`"
                _m5_rows.append(f"| {_row_i} | {ref} | {_cards_str_to_pills(cards)} | "
                      f"{arche_disp} | {hook or '—'} |")
            _m5_blk = hand_evidence_table_block("iii9-analyst-picks", _m5_hdr, _m5_sep, _m5_rows)
            doc.write_block(_m5_blk)
            doc.w("")
        # Structural candidates — NOT presented as picks. Facts only.
        if provisional:
            doc.w(f"**Structural screen — unpromoted candidates ({len(provisional)})** "
                  f"— the screen surfaced these as possibly "
                  f"well-played, but \"well played\" is an analyst call. No "
                  f"archetype is assigned until an analyst writes a Pick "
                  f"verdict; the columns below are the structural facts only.")
            doc.w("")
            _m6_hdr = "| # | Hand Reference | Cards | Structural signal |"
            _m6_sep = "|---|---|---|---|"
            _m6_rows = []
            _row_i = 0
            for hid, arch, reasons, sc in provisional:
                _row_i += 1
                h = (s.get('_hands_by_id', {}) or {}).get(hid, {})
                cards = ''.join(h.get('cards', [])) if h else '—'
                why = '; '.join(r for r in reasons
                                if not str(r).startswith('context:')) or '—'
                if len(why) > 110:
                    why = why[:107] + '…'
                ref = _href(h, s['_hands_by_id']) if h else f"`{hid[-8:]}`"
                _m6_rows.append(f"| {_row_i} | {ref} | {_cards_str_to_pills(cards)} | {why} |")
                # Citation fires here — same execution point as before migration.
                _state._record_citation_explicit(
                    hid, 'sec-4-3', "S4.3 Pokerbot's Picks")
            _m6_blk = hand_evidence_table_block("iii9-provisional", _m6_hdr, _m6_sep, _m6_rows)
            doc.write_block(_m6_blk)
            doc.w("")
            doc.w(f"*{len(provisional)} candidate(s) screened from "
                  f"{len(_scored)} structural candidates. To turn one into a "
                  f"Pick, add a Pick analyst verdict with an `archetype` "
                  f"field — until then it is a lead, not a verdict.*")
            doc.w("")
        # B173 (Ron 2026-05-24): the screened-candidates table is structural
        # QA output. B191: now excludes hands already promoted to a provisional
        # Pick above — this is the remainder. Collapsed by default.
        _open_cands = [c for c in _bp_cands
                       if isinstance(c, dict) and c.get('id')
                       and c['id'] not in _analyst_pick_ids
                       and c['id'] not in _provisional_ids
                       and c['id'] not in _adjudicated_ids]
        if _open_cands:
            doc.w(f"<details><summary><strong>▸ Other candidates screened "
                  f"({len(_open_cands)})</strong> — structural screen, scored "
                  f"below the promotion threshold. Expand to review; full hand "
                  f"grid for each is in XIV.B Quick Lookups.</summary>")
            doc.w("")
            _m7_hdr = "| Hand Reference | Cards | Pos | Screened On |"
            _m7_sep = "|---|---|---|---|"
            _m7_rows = []
            for c in _open_cands:
                hid = c['id']
                h = (s.get('_hands_by_id', {}) or {}).get(hid, {})
                cards = ''.join(h.get('cards', [])) if h else '—'
                reasons = '; '.join(
                    (c.get('bestplay_screen', {}) or {}).get('reasons', [])) or '—'
                ref = _href(h, s['_hands_by_id']) if h else f"`{hid[-8:]}`"
                _m7_rows.append(f"| {ref} | {_cards_str_to_pills(cards)} | "
                      f"{h.get('position', '—')} | {reasons} |")
                # Citation fires here — same execution point as before migration.
                _state._record_citation_explicit(
                    hid, 'sec-4-3', "S4.3 Pokerbot's Picks (Candidates)")
            # <details> boundary: block is INSIDE the <details>; open/close tags
            # are prose OUTSIDE. Do NOT move <details> into the block.
            _m7_blk = hand_evidence_table_block("iii9-open-cands", _m7_hdr, _m7_sep, _m7_rows)
            doc.write_block(_m7_blk)
            doc.w("")
            doc.w("</details>")
            doc.w("")


def _emit_sub_read_dep_picks(doc, s, rd, hands):
    """Item 11: Read-Dependent subsegment — up to 15 truly read-dependent hands."""
    analyst = rd.get('analyst_commentary', {}) or {}
    hands_by_id = {h.get('id', ''): h for h in hands}
    rd_quant = rd.get('read_dependent_quant', {}) or {}

    # Collect III.4 hands — truly read-dependent
    iii4_entries = []
    for hid, cmt in analyst.items():
        if (isinstance(cmt, dict)
                and (cmt.get('verdict', '') or '').startswith('III.4')
                and hid.startswith('TM')):
            iii4_entries.append((hid, cmt))

    # Sort by net BB (biggest losses first — most impactful reads)
    iii4_entries.sort(key=lambda t: (hands_by_id.get(t[0], {}).get('net_bb', 0)))

    _CAP = 15
    n_total = len(iii4_entries)
    showing = iii4_entries[:_CAP]

    doc.w("")
    doc.w(f"**📖 Read-Dependent** — *hands whose verdict genuinely depends on "
          f"a villain-specific read ({n_total} total"
          + (f", showing {_CAP} of {n_total}" if n_total > _CAP else "")
          + ")*")
    doc.w("")
    if not showing:
        doc.w("⚪ No read-dependent hands this session.")
        doc.w("")
        return

    doc.w("| # | Hand | Cards | Net BB | Pop Baseline | Read/Axis |")
    doc.w("|---|---|---|---:|---|---|")
    for i, (hid, cmt) in enumerate(showing, 1):
        h = hands_by_id.get(hid)
        ref = _hand_ref(h) if h else f"`{hid[-8:]}`"
        cards = (_cards_str_to_pills(''.join(h.get('cards', [])))
                 if h else '—') or '—'
        net_bb = (h.get('net_bb') if h else 0) or 0
        axis = cmt.get('decision_axis', '') or '—'
        # Solver pop-baseline from read-dependent quant
        _q = rd_quant.get(hid)
        if _q and _q.get('solvable'):
            _vp = _q.get('verdict_pop', 'CALL')
            _pev = _q.get('ev_call_pop_bb', 0.0)
            if _vp == 'FOLD':
                pop_cell = f"🔴 FOLD ({_pev:+.1f})"
            elif _vp == 'INDIFF':
                pop_cell = "🟡 ~indiff"
            else:
                pop_cell = "🟢 CALL ✓"
        else:
            pop_cell = "*pre-river*"
        doc.w(f"| {i} | {ref} | {cards} | {net_bb:+.1f} | {pop_cell} | {axis} |")
    doc.w("")


def _emit_sub_gto_standard_picks(doc, s, rd, hands):
    """Item 11: GTO-Standard subsegment — up to 15 III.0 hands sorted by thinness."""
    analyst = rd.get('analyst_commentary', {}) or {}
    hands_by_id = {h.get('id', ''): h for h in hands}
    rd_quant = rd.get('read_dependent_quant', {}) or {}

    # Collect III.0 GTO-Standard hands
    iii0_entries = []
    for hid, cmt in analyst.items():
        if (isinstance(cmt, dict)
                and (cmt.get('verdict', '') or '').startswith('III.0')
                and hid.startswith('TM')):
            iii0_entries.append((hid, cmt))

    # Sort by thinness: smallest |EV gap| = thinnest decision = listed first.
    # Use read_dependent_quant's ev_call_pop_bb as the EV-gap proxy (closest
    # to zero = thinnest). Hands without solver data sort last.
    def _thinness_key(t):
        hid = t[0]
        _q = rd_quant.get(hid)
        if _q and _q.get('solvable') and _q.get('ev_call_pop_bb') is not None:
            return (0, abs(_q['ev_call_pop_bb']))
        # Fallback: no solver data — sort by |net_bb| (smaller = thinner)
        h = hands_by_id.get(hid)
        return (1, abs((h.get('net_bb') if h else 0) or 0))

    iii0_entries.sort(key=_thinness_key)

    _CAP = 15
    n_total = len(iii0_entries)
    showing = iii0_entries[:_CAP]

    doc.w(f"**⚖️ GTO-Standard** — *forced/standard decisions with no read "
          f"required ({n_total} total"
          + (f", showing {_CAP} of {n_total}" if n_total > _CAP else "")
          + ")*")
    doc.w("")
    if not showing:
        doc.w("⚪ No GTO-Standard hands this session.")
        doc.w("")
        return

    doc.w("| # | Hand | Cards | Net BB | Outcome | Spot |")
    doc.w("|---|---|---|---:|---|---|")
    for i, (hid, cmt) in enumerate(showing, 1):
        h = hands_by_id.get(hid)
        ref = _hand_ref(h) if h else f"`{hid[-8:]}`"
        cards = (_cards_str_to_pills(''.join(h.get('cards', [])))
                 if h else '—') or '—'
        net_bb = (h.get('net_bb') if h else 0) or 0
        # Outcome sub-label (dominating, lost_flip, coin_flip, etc.)
        _oce, _oct = _outcome_label(cmt, default=('⚖️', 'Standard'))
        outcome_cell = f"{_oce} {_oct}"
        spot = (cmt.get('spot') or '—')
        if len(spot) > 80:
            spot = spot[:78] + '…'
        doc.w(f"| {i} | {ref} | {cards} | {net_bb:+.1f} | {outcome_cell} | {spot} |")
    doc.w("")


# ============================================================
# SECTION IV — PRE-FLOP ENGINE
# ============================================================

