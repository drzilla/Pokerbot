"""Top-level orchestration: render_html, render_md, generate_report_draft."""

VERSION = "v8.12.0"

from gem_report_draft import _state
from gem_report_draft._helpers import (_wilson_ci, _clr, _clr_min, _clr_naive,
    _pctc, _stat_signal, _verdict_ci, _verdict_pct, _hand_ref, _hand_ref_short,
    _xref, _stat_row, _stat_row_pct, _aim_lookup_from_watchlist, _back_to_kpis,
    _compact_range, _run_emoji, _outcome_label, _CI_Z_DEFAULT, _MIN_N_FOR_SIGNAL,
    _RANK_ORD, _break_at_sentences, _href, _emit_correct_ranges, _new_badge)
from gem_report_draft._html import (Doc, _card_html, _cards_html,
    _cards_str_to_pills, _cards_text_to_pills, _md_inline, _html_escape,
    _html_wrap, _sort_cards_desc, _describe_made_hand, _SUIT_HTML,
    _RANK_VALUES, _SUIT_VALUES)
from gem_report_draft._hand_grid import (_render_hand_grid_table,
    _key_decision_action_class, _pick_key_action_idx, _hero_actions_by_street_from_app,
    _hero_action_verbs_by_street_from_app)
from gem_report_draft.tldr import (_emit_tldr, _emit_leak_watchlist, _emit_legend,
    _emit_results_attribution)
from gem_report_draft.sections_financial import (_emit_daily_summary_table,
    _emit_skill_index_movement, _emit_section_i, _emit_section_ii,
    _emit_ii_verdict_kpis, _emit_ii_mental_bluff)
from gem_report_draft.sections_mistakes import (_emit_mental_game, _emit_section_iii,
    _emit_iii_punts_mistakes, _emit_iii_strategic_leaks,
    _emit_iii_cleared_justified, _emit_iii_clinical_picks)
from gem_report_draft.sections_iv_xii import (_emit_section_iv, _emit_section_v,
    _emit_section_vi, _emit_section_vii, _emit_section_viii, _emit_section_ix,
    _emit_section_x, _emit_section_xi, _emit_section_xii)
from gem_report_draft.sections_issue_explorer import _emit_issue_explorer
from gem_report_draft.sections_xiii import _emit_section_xiii
from gem_report_draft.sections_xiv import (_emit_section_xiv_appendix,
    _compute_per_tourney_pnl)

import gem_made_hands as mh
import gem_issue_collector
from collections import defaultdict

def render_html(stats, report_data, hands, sections=None,
                strict_lint=None, qa_block=None, gtow_links=None):
    _resolve_gtow_flag(report_data, gtow_links)
    doc = _build(stats, report_data, hands, sections=sections)
    # v8.7.7: attach hands ref for board contradiction lint
    stats['_hands_ref'] = hands
    _lint_phase(doc, strict_lint, qa_block, stats=stats, report_data=report_data)
    return doc.render_html()


def render_md(stats, report_data, hands, sections=None,
              strict_lint=None, qa_block=None, gtow_links=None):
    _resolve_gtow_flag(report_data, gtow_links)
    doc = _build(stats, report_data, hands, sections=sections)
    stats['_hands_ref'] = hands
    _lint_phase(doc, strict_lint, qa_block, stats=stats, report_data=report_data)
    return doc.render_md()


def render_both(stats, report_data, hands, sections=None,
                strict_lint=None, qa_block=None, gtow_links=None):
    """Build once, render both HTML + MD. Avoids the double _build() cost
    when both formats are needed (pipeline default).  Ron 2026-05-30."""
    _resolve_gtow_flag(report_data, gtow_links)
    doc = _build(stats, report_data, hands, sections=sections)
    stats['_hands_ref'] = hands
    _lint_phase(doc, strict_lint, qa_block, stats=stats, report_data=report_data)
    return doc.render_html(), doc.render_md()


def _resolve_gtow_flag(report_data, gtow_links=None):
    """Resolve the gtow_links feature flag and stamp it on report_data.

    Same pattern as _lint_phase reads GEM_STRICT_LINT / GEM_QA_BLOCK:
    explicit param wins; env-var fallback when None.  Default OFF.
    """
    import os
    if gtow_links is None:
        gtow_links = os.environ.get(
            'GEM_GTOW_LINKS', '').lower() in ('1', 'true', 'yes')
    report_data['gtow_links'] = bool(gtow_links)


def _lint_phase(doc, strict_lint=None, qa_block=None, stats=None, report_data=None):
    """Phase 3 lint gate — runs after _build(), before render.

    Reads GEM_STRICT_LINT / GEM_QA_BLOCK env vars when params are None,
    so gem_run.py can set them without touching gem_analyzer.py.
    """
    import os
    if strict_lint is None:
        strict_lint = os.environ.get(
            'GEM_STRICT_LINT', '').lower() in ('1', 'true', 'yes')
    if qa_block is None:
        qa_block = os.environ.get(
            'GEM_QA_BLOCK', '').lower() in ('1', 'true', 'yes')
    import gem_report_lint
    gem_report_lint.lint_and_gate(
        doc, strict_lint=strict_lint, qa_block=qa_block,
        stats=stats, report_data=report_data)


def _build(stats, report_data, hands, sections=None):
    """Build a Doc with all sections.

    sections : list[str] | None
        If None or ['ALL'], emits the full I-XIII outline (default).
        Otherwise pass a list of Roman section labels (e.g. ['III', 'IV', 'XIII'])
        to render only those. The TL;DR + Legend + TOC always render so the
        partial output is still navigable.
    """
    s = dict(stats)
    rd = report_data
    doc = Doc()

    # Compute per-tournament P&L from hands (analyzer doesn't carry it)
    s['_per_tourney_pnl'] = _compute_per_tourney_pnl(hands, rd.get('buyin_breakdown', []))
    # Table-size breakdown from hands
    s['_table_size_breakdown'] = _compute_table_size_breakdown(hands)
    # Made-hands stats
    s['_made_hands'] = mh.compute(hands)
    # Per-id hand lookup (used by _href when entity has just id)
    s['_hands_by_id'] = {h.get('id', ''): h for h in hands}

    # B43 (v7.44): pre-compute the appendix hand-id set so _hand_ref can
    # auto-link citations to appendix anchors. v7.45 (Ron 2026-05-11): now
    # uses the broader `appendix_hand_ids_all` from prepare_report_data which
    # includes all referenced hand_ids (busts, mistakes, deviations, clinical
    # examples, etc.) — so EVERY hand citation in the body becomes a link.
    _all_app_ids = rd.get('appendix_hand_ids_all')
    if _all_app_ids:
        _appendix_ids = set(_all_app_ids)
    else:
        # Fallback to original narrow logic if pre-pass didn't run
        _analyst_pre = (rd.get('analyst_commentary') or {})
        _rev = rd.get('reviewed_mistakes', {}) or {}
        _appendix_ids = set()
        for m in (_rev.get('needs_review') or []):
            if m.get('id'): _appendix_ids.add(m.get('id'))
        for hid, cmt in _analyst_pre.items():
            if isinstance(cmt, dict) and hid.startswith('TM'):
                _appendix_ids.add(hid)
    # B133 (Ron 2026-05-20): also fold in III.2 __synthesis__ strategic-leak
    # example hand_ids. The synthesis is attached to rd after prepare_report_
    # data runs, so it must be merged here at render time — otherwise an
    # example hand with no separate analyst entry has a dead #sec-app-hand link.
    _synth_b133 = (rd.get('analyst_commentary') or {}).get('__synthesis__') or {}
    for _lk in (_synth_b133.get('leaks') or {}).values():
        for _ex in (_lk.get('examples') or []):
            _eid = _ex if isinstance(_ex, str) else (
                   _ex.get('hand_id') if isinstance(_ex, dict) else None)
            if _eid:
                _appendix_ids.add(_eid)
    # B188 (Ron review 2026-05-25): PERMANENT FIX for the recurring no-link
    # bug (B43 / B133 / B184 — 4th occurrence). The old approach hand-listed
    # every section that cites hands; each new section silently re-broke it.
    # Root cause: a hand-id allowlist that must be manually extended.
    # Fix: recursively walk rd + s and harvest EVERY TM-prefixed value found
    # at an `id` / `hand_id` key, anywhere, at any depth. Any section that
    # renders a hand pulls it from some list in rd/s, so this structurally
    # cannot miss one. XIV.B already excludes harvested-but-uncited ids
    # (it groups stubs by the citation registry), so over-harvesting is free.
    def _deep_harvest(obj, out, _depth=0):
        if _depth > 12:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ('id', 'hand_id') and isinstance(v, str) \
                        and v.startswith('TM'):
                    out.add(v)
                else:
                    _deep_harvest(v, out, _depth + 1)
        elif isinstance(obj, (list, tuple)):
            for it in obj:
                _deep_harvest(it, out, _depth + 1)
    _deep_harvest(rd, _appendix_ids)
    _deep_harvest(s, _appendix_ids)
    # XIV.B builds its stub list from rd['appendix_hand_ids_all'] directly, so
    # the merged set must be written back, not just passed to the setter.
    rd['appendix_hand_ids_all'] = sorted(_appendix_ids)
    # Bug A fix: reset BEFORE set — _reset_citations() wipes _APPENDIX_HAND_IDS,
    # so setting it first then resetting destroys the harvested set.
    _state._reset_citations()
    _state._set_appendix_hand_ids(_appendix_ids)

    _emit_header(doc, s, rd)
    _emit_tldr(doc, s, rd)
    # B167 (Ron 2026-05-24, formatting spec 1.1): ToC immediately after the
    # Executive TL;DR — before the section emitters.
    doc.w("<<TOC>>")
    doc.w("---")
    doc.w("")
    # Phase 4.8: Leak Watchlist moved INTO S6 KPIs as sec-6-0 "Metric Watchlist".
    # Legend removed per user request (Phase 4.8 section reorg).

    # Phase 4 section filter: --section accepts S-notation (S1, S2, …S18)
    # or legacy Roman (I, II, …XIV). Roman labels expand to their S-segments
    # so `--section III` renders S2+S3+S4+S13 (the four III sub-segments).
    _ROMAN_TO_S = {
        'I': ['S1'], 'II': ['S6', 'S7'], 'III': ['S2', 'SIE', 'S3', 'S4', 'S13'],
        'IE': ['SIE'],
        'IV': ['S5'], 'V': ['S8'], 'VI': ['S9'], 'VII': ['S10'],
        'VIII': ['S11'], 'IX': ['S12'], 'X': ['S14'], 'XI': ['S15'],
        'XII': ['S16'], 'XIII': ['S17'], 'XIV': ['S18'],
    }
    want = None
    if sections and 'ALL' not in [str(x).upper() for x in sections]:
        want = set()
        for x in sections:
            xu = str(x).upper()
            if xu in _ROMAN_TO_S:
                want.update(_ROMAN_TO_S[xu])
            else:
                want.add(xu)

    # Issue Explorer (v8.1.0): collect issues from ALL pipeline sources into
    # a unified tiered list. This runs before section emitters so rd is populated.
    if 'issue_explorer_issues' not in rd:
        try:
            rd['issue_explorer_issues'] = gem_issue_collector.collect_issues(s, rd, hands)
            rd['issue_explorer_coverage'] = gem_issue_collector.build_coverage_report(s, rd, hands)
        except Exception as _ie_err:
            import logging
            logging.getLogger('gem').warning('Issue collector failed: %s', _ie_err)
            rd['issue_explorer_issues'] = []
            rd['issue_explorer_coverage'] = []

    # Phase 4.8: full 18-segment order matching user's tab-to-subsection mapping.
    # S16 Glossary RESTORED (was wrongly removed). Legend removed (separate).
    # Subsections reorganized: each emitter now contains the correct subsections
    # per the user's exact mapping (Coach, Result, KPIs, etc.).
    section_emitters = [
        # v8.2.1: Issue Explorer moved to #2 (between Summary and Result)
        # ('S7',  _emit_ii_mental_bluff),      # Coach — in dashboard
        ('SIE', _emit_issue_explorer),         # Issue Explorer — triage table (v8.2.0)
        ('S1',  _emit_section_i),              # Result — P&L, All-Ins, card quality, coolers, arc
        ('S5',  _emit_section_viii),           # Action Items — promoted leaks, drills, GTO shortlist
        ('S6',  _emit_ii_verdict_kpis),        # KPIs — watchlist, cheat sheet, KPIs, mental game, exploits, bluff
        ('S2',  _emit_iii_punts_mistakes),     # Top hands — punts, mistakes, large-loss, picks
        ('S3',  _emit_iii_strategic_leaks),    # Leaks — legacy details (collapsed when IE has parity)
        ('S4',  _emit_iii_clinical_picks),     # Tourney type — bounty/PKO
        ('S8',  _emit_section_iv),             # Preflop
        ('S9',  _emit_section_v),              # Postflop SRP
        ('S10', _emit_section_vi),             # Postflop 3BP/4BP
        ('S11', _emit_section_vii),            # Mechanics — facing bets, sizing, stack depth, river, bet-fold, steal, bet/check, archetype
        ('S13', _emit_iii_cleared_justified),  # Aggression — AF, CR freq, CR made, drills, 3-bet sizing, bluff all streets
        ('S12', _emit_section_ix),             # Progress — tracker + learnings
        ('S14', _emit_section_x),              # QA
        ('S15', _emit_section_xi),             # Raw Stats
        ('S16', lambda doc, s, rd, hands: _emit_section_xii(doc)),  # Glossary
        ('S17', _emit_section_xiii),           # Deviation
        ('S18', _emit_section_xiv_appendix),   # Appendix
    ]
    # v8.8.7 (Ron 2026-06-08): HA3 budget planner can trim cited P2 appendix
    # cards out of appendix_hand_ids_all. Those hands are intentionally dropped
    # (handAvailability='budget_trimmed', graceful UI fallback) and must NOT trip
    # the orphan-pill blocker below. Capture trimmed IDs at loop scope so the
    # gate can exclude them.
    _budget_trimmed_ids = set()
    for label, fn in section_emitters:
        if want is not None and label not in want:
            continue
        # Phase 4.5 (§2.2): snapshot citations before emitter to detect
        # which hands this section referenced — for the relevant-hands list.
        _cite_before = {hid: set(secs) for hid, secs in _state._CITATIONS.items()}
        # v8.4.3: BEFORE appendix emitter, harvest ALL hand IDs from data-hids
        # attributes in already-emitted lines. This catches EVERY hand referenced
        # by ANY hand-list-trigger, not just those registered via _popup_example_ids.
        if label == 'S18':
            import re as _re_hids
            _hids_pat = _re_hids.compile(r'data-hids="([^"]*)"')
            # v8.8.6 Phase HA1: collect ALL referenced hids for audit
            _all_body_hids = set()
            for _line in doc.lines:
                _m = _hids_pat.search(str(_line))
                if _m:
                    for _hid in _m.group(1).split(','):
                        _hid = _hid.strip()
                        if _hid:
                            _state._APPENDIX_HAND_IDS.add(_hid)
                            _all_body_hids.add(_hid)
            _late_ids = _state._APPENDIX_HAND_IDS - set(rd.get('appendix_hand_ids_all', []))
            if _late_ids:
                _all_ids = set(rd.get('appendix_hand_ids_all', []))
                _all_ids |= _late_ids
                rd['appendix_hand_ids_all'] = sorted(_all_ids)

            # v8.8.6 HA3-fix: register exploit opportunity hands as P0
            # Exploit miss/good hands MUST have detail cards for coaching blocks
            _vi = s.get('villain_intel', {}) or {}
            _exp_opps = _vi.get('exploit_opportunities', []) or []
            for _eo in _exp_opps:
                _eo_hid = _eo.get('hand_id', '')
                if _eo_hid:
                    _state._register_hand_priority(_eo_hid, 0)  # P0: exploit hands
                    _state._APPENDIX_HAND_IDS.add(_eo_hid)
                    # Ensure in appendix set
                    if _eo_hid not in set(rd.get('appendix_hand_ids_all', [])):
                        _all_ids_eo = list(rd.get('appendix_hand_ids_all', []))
                        _all_ids_eo.append(_eo_hid)
                        rd['appendix_hand_ids_all'] = _all_ids_eo

            # v8.8.6 Phase HA3: priority-based budget planner
            # Assign P2 default to any late-harvest IDs without explicit priority
            _prios = _state._APPENDIX_HAND_PRIORITIES
            # v8.14.3 Issue 3 (Ron 2026-06-15): analyst-judged hands MUST survive
            # the byte budget. Previously only exploit/issue-explorer hands were P0,
            # so a hand the analyst graded a MISTAKE could render 'budget_trimmed'
            # (e.g. TM6078122219, III.2). Promote every hand carrying an analyst
            # verdict: P0 for actual mistakes (III.1/III.2) and any significant-loss
            # / critical-need hand; P1 for other graded verdicts (III.3/III.4/III.5/
            # I.7). Significant-loss + critical-need hands are P0 even without a
            # verdict. Normalize to the 8-digit IDs the budget uses. _ANALYST_FULL_IDS
            # also drives the trimmed-duplicate suppression below.
            _ac_fix = (rd.get('analyst_commentary') or {})
            _p0_loss_fix = (set(rd.get('_significant_loss_ids', []) or [])
                            | set(rd.get('_critical_need_ids', []) or []))
            _analyst_full_ids = set()
            for _ac_hid, _ac_cmt in _ac_fix.items():
                if str(_ac_hid).startswith('__') or not isinstance(_ac_cmt, dict):
                    continue
                _vd = str(_ac_cmt.get('verdict', '') or '')
                _is_mistake = _vd.startswith('III.1') or _vd.startswith('III.2')
                _pri_target = 0 if (_is_mistake or _ac_hid in _p0_loss_fix) else 1
                for _cand in {_ac_hid, _ac_hid[-8:]}:
                    _state._register_hand_priority(_cand, _pri_target)
                    _analyst_full_ids.add(_cand)
            for _sl_hid in _p0_loss_fix:
                for _cand in {_sl_hid, _sl_hid[-8:]}:
                    _state._register_hand_priority(_cand, 0)
            for _hid in rd.get('appendix_hand_ids_all', []):
                if _hid not in _prios:
                    _prios[_hid] = 2  # P2 default for unclassified
            # Sort by priority (P0 first), then alphabetical for stability
            _all_with_prio = [(hid, _prios.get(hid, 2))
                              for hid in rd.get('appendix_hand_ids_all', [])]
            _all_with_prio.sort(key=lambda x: (x[1], x[0]))
            # Budget: ~2.5 KB per hand card. Soft cap 15 MB, hard cap 20 MB.
            _AVG_CARD_KB = 2.5
            _SOFT_CAP_KB = 15 * 1024       # 15 MB
            _HARD_CAP_KB = 20 * 1024       # 20 MB
            _body_kb = sum(len(str(l)) for l in doc.lines) / 1024
            _card_budget_kb = _SOFT_CAP_KB - _body_kb
            _max_cards = max(int(_card_budget_kb / _AVG_CARD_KB), 200)
            _budget_ids = []
            _trimmed_ids = set()
            for _hid, _pri in _all_with_prio:
                if len(_budget_ids) < _max_cards or _pri <= 0:
                    # P0 always survives, others within budget
                    _budget_ids.append(_hid)
                else:
                    _trimmed_ids.add(_hid)
            # v8.14.3 Issue 3: a hand with a full XIV.A analyst entry must never
            # ALSO render a trimmed stub. Rescue any analyst-full id that slipped
            # into the trim set so the body never shows a full entry + a dup stub.
            _rescued = _trimmed_ids & _analyst_full_ids
            if _rescued:
                _budget_ids.extend(sorted(_rescued))
                _trimmed_ids -= _rescued
            if _trimmed_ids:
                rd['appendix_hand_ids_all'] = _budget_ids
                _state._APPENDIX_HAND_IDS -= _trimmed_ids
                _budget_trimmed_ids |= _trimmed_ids
                _state._BUDGET_TRIMMED_IDS |= _trimmed_ids
            # Serialize priority map for frontend analytics
            import json as _json_prio
            _prio_summary = {}
            for _p in (0, 1, 2, 3):
                _cnt = sum(1 for h, p in _all_with_prio if p == _p and h not in _trimmed_ids)
                if _cnt:
                    _prio_summary[f'P{_p}'] = _cnt
            if _trimmed_ids:
                _prio_summary['trimmed'] = len(_trimmed_ids)
            doc._extra_js.append(
                f'window.handPriorityBudget={_json_prio.dumps(_prio_summary)};')

            # v8.8.6 Phase HA1: build handReferenceAudit + handAvailability
            # V25.3 item 6: canonicalize to 8-digit IDs for JS lookup consistency
            def _norm8(hid):
                return hid[-8:] if isinstance(hid, str) and len(hid) > 8 else hid

            _app_set = set(rd.get('appendix_hand_ids_all', []))
            _hands_by_id = s.get('_hands_by_id', {})
            # Precompute normalized sets for O(1) lookup
            _norm_body = {_norm8(h) for h in _all_body_hids}
            _app_set_norm = {_norm8(h) for h in _app_set}
            _trimmed_norm = {_norm8(t) for t in _trimmed_ids}
            _hands_norm = {_norm8(k) for k in _hands_by_id}

            _ha_avail = {}
            for _hid_n in _norm_body:
                if _hid_n in _app_set_norm:
                    _ha_avail[_hid_n] = 'available'
                elif _hid_n in _trimmed_norm:
                    _ha_avail[_hid_n] = 'budget_trimmed'
                elif _hid_n not in _hands_norm:
                    _ha_avail[_hid_n] = 'non_replayable'
                else:
                    _ha_avail[_hid_n] = 'not_rendered'
            _ha_missing = {h for h, st in _ha_avail.items() if st != 'available'}
            import json as _json_ha
            _ha_audit = {
                'total_referenced': len(_norm_body),
                'detail_available': len(_norm_body) - len(_ha_missing),
                'missing_detail': len(_ha_missing),
                'by_reason': {},
            }
            for _reason in ('not_rendered', 'non_replayable', 'budget_trimmed'):
                _cnt = sum(1 for v in _ha_avail.values() if v == _reason)
                if _cnt:
                    _ha_audit['by_reason'][_reason] = _cnt
            doc._extra_js.append(
                f'window.handReferenceAudit={_json_ha.dumps(_ha_audit)};')
            doc._extra_js.append(
                f'window.handAvailability={_json_ha.dumps(_ha_avail)};')
            # v8.12.8: static hand index for hand-list popups. Lazy-mode
            # articles are empty shells until PBLazy inflates them, so the
            # popup's DOM scrape rendered blank Position/Cards/Net columns
            # until a hand had been opened once. p=position, c=hole cards
            # compact ('8s6d'), n=net BB. Index-first, DOM-scrape fallback.
            _hbyn = {_norm8(k): v for k, v in _hands_by_id.items()}
            _hi = {}
            for _hid_n in sorted(_app_set_norm):
                _hh = _hbyn.get(_hid_n)
                if not isinstance(_hh, dict):
                    continue
                _e = {}
                if _hh.get('position'):
                    _e['p'] = _hh['position']
                # v8.12.8 QA3: opener position — the "Vs Pos" column in
                # defend popups showed HERO's position (always BB) instead
                # of who Hero defended against.
                if _hh.get('opener_position'):
                    _e['o'] = _hh['opener_position']
                _hcards = _hh.get('cards') or []
                if _hcards:
                    _e['c'] = ''.join(str(c) for c in _hcards[:2])
                _nb = _hh.get('net_bb')
                if isinstance(_nb, (int, float)):
                    _e['n'] = round(_nb, 1)
                if _e:
                    _hi[_hid_n] = _e
            if _hi:
                doc._extra_js.append(
                    'window.handIndex='
                    + _json_ha.dumps(_hi, separators=(',', ':')) + ';')
            _cc = rd.get('coaching_cards', {})
            if _cc:
                import json as _json_cc
                _cc_short = {k[-8:]: v for k, v in _cc.items()}
                doc._extra_js.append(
                    f'window.coachingCards={_json_cc.dumps(_cc_short)};')
        fn(doc, s, rd, hands)

    # Phase 4.5: Universal-pill build gate (§3) — every cited hand must
    # have an appendix card.  Hard build failure if orphan pills exist.
    # This is the "gate, not a hope" enforcement.
    # v8.8.7: budget-trimmed hands are an INTENTIONAL drop (handAvailability=
    # 'budget_trimmed' with a graceful popup fallback), not an orphan — exclude
    # them so the HA3 planner and the universal-pill gate stop contradicting.
    _cited_ids = set(_state._CITATIONS.keys())
    _appendix_set = set(rd.get('appendix_hand_ids_all', []))
    _orphan_pills = _cited_ids - _appendix_set - _budget_trimmed_ids
    if _orphan_pills:
        raise RuntimeError(
            f"BLOCKER: {len(_orphan_pills)} orphan pill(s) — cited but no "
            f"appendix card: {', '.join(sorted(_orphan_pills))}")
    if _budget_trimmed_ids & _cited_ids:
        print(f"  HA3: {len(_budget_trimmed_ids & _cited_ids)} cited hand(s) "
              f"budget-trimmed (graceful 'budget_trimmed' fallback in popup)")

    # Phase 4.6 B3: populate topbar KPIs for the sticky header
    # Phase 4.8 C2: expanded to 12 stat cards (10 PDF + Net + ROI)
    vol = s.get('volume', {})
    _csv = s.get('csv_row', {})
    _core = s.get('core', {})
    _usd_ov = rd.get('usd_overlay', {}) or {}
    _hh_int = _usd_ov.get('hh_intersect_totals') or _usd_ov.get('totals') or {}
    _punts = s.get('punts', {})
    # v8.14.3 Issue 1 (Ron 2026-06-15): SINGLE financial contract. When the USD
    # overlay is parsed, usd_overlay.totals is CANONICAL for cost/cash/net/ROI/
    # bullets/tournament-count, and ABI is derived from the SAME cost/bullets the
    # by-day TOTAL row uses (no per-field source mixing, no max() denominator).
    # The filename system is the fallback ONLY when no parsed overlay exists, kept
    # byte-identical so no-overlay sessions do not drift.
    _ov_tot = _usd_ov.get('totals') or {}
    _ov_parsed = (_usd_ov.get('status') == 'parsed') and bool(_ov_tot)
    _filename_inv = rd.get('total_invested') or 0
    if _ov_parsed:
        _canon_inv = _ov_tot.get('total_cost') or _filename_inv
        _canon_bullets = _ov_tot.get('n_bullets') or vol.get('bullets', 0)
        _canon_net = _ov_tot.get('total_net')
        _canon_roi = _ov_tot.get('roi_pct')
        _canon_tourneys = _ov_tot.get('n_tournaments') or 0
        _canon_abi = (_canon_inv / _canon_bullets) if _canon_bullets else rd.get('avg_buyin')
    else:
        _canon_inv = _filename_inv
        _canon_bullets = (_ov_tot.get('n_bullets') or vol.get('bullets', 0))
        _canon_net = _hh_int.get('total_net')
        _canon_roi = (_canon_net / _canon_inv * 100) if _canon_inv and _canon_net is not None else _hh_int.get('roi_pct')
        _canon_tourneys = (vol.get('tournaments', 0)
                           or len(s.get('tournament_list', []))
                           or (_usd_ov.get('totals') or {}).get('n_tournaments', 0)
                           or len(s.get('_per_tourney_pnl', {})))
        _canon_abi = rd.get('avg_buyin')   # filename system unchanged when no overlay
    # 44-vs-43: the HH-count includes an unresolved 2-day event with no game
    # summary; the canonical (settled) count is the overlay's n_tournaments.
    # Annotate the gap so the same count shows everywhere with an explanation.
    _unresolved_hh = _usd_ov.get('unresolved_hh_tournaments') or []
    _nt_note = (f"{len(_unresolved_hh)} in progress"
                if (_ov_parsed and _unresolved_hh) else '')
    doc._topbar_kpis = {
        'player': rd.get('player_name', 'Knockman'),
        'date': vol.get('date', ''),
        'n_hands': vol.get('hands', 0),
        # v8.14.3 Issue 1: canonical (overlay when parsed) tournament count +
        # in-progress annotation; ABI/Invested/Net/ROI all from the same source.
        'n_tourneys': _canon_tourneys,
        'n_tourneys_note': _nt_note,
        'bullets': _canon_bullets,
        'avg_buyin': _canon_abi,
        'total_invested': _canon_inv,
        'net': _canon_net,
        'roi': _canon_roi,
        'bb100': _csv.get('BB_per_100', _core.get('bb_per_100')),
        'ev_bb100': _core.get('ev_bb_per_100'),  # kept for backward compat
        # True EV = fully variance-adjusted (all 4 layers). This is the
        # single number that answers "how well did I play, removing all luck."
        'true_ev': (rd.get('results_attribution') or {}).get(
            'implied_true_ev_extended_per_100'),
        # B257: use post-analyst confirmed rates from discipline_tier when
        # available (includes analyst III.1/III.2 verdicts); fall back to
        # pre-analyst detector rates when no analyst file was provided.
        'punts_per_100': rd.get('discipline_tier', {}).get(
            'punts_per_100', _punts.get('per_100')),
        'mistakes_per_100': rd.get('discipline_tier', {}).get(
            'canonical_mistakes_per_100', s.get('mistakes_per_100')),
        # Fallback: csv_row → skill_index_movement today → core
        'skill_index': (_csv.get('Skill_Index')
                        or (rd.get('skill_index_movement', {}).get('today', {}) or {}).get('skill_index')
                        or _core.get('skill_index')),
    }

    # Phase 4.6 B4: populate nav section list for the sidebar
    # Phase 4.8: nav labels + subtitles aligned with user's desired tab names.
    # Order determined by section_emitters above; labels here are keyed by S-number.
    _NAV_SUBTITLES = {
        'S7': 'discipline & process', 'S1': 'variance vs skill',
        'S6': 'verdict & KPIs', 'S2': 'punts & mistakes',
        'SIE': 'tiered issues & coverage',
        'S3': 'legacy leak details', 'S4': 'bounty / PKO',
        'S8': 'preflop engine', 'S9': 'postflop SRP',
        'S10': '3BP & 4BP', 'S11': 'macro postflop',
        'S13': 'aggression profile', 'S5': 'action card & GTO',
        'S12': 'leak persistence', 'S14': 'bug tracker',
        'S15': 'stat reference', 'S16': 'terminology & symbols',
        'S17': 'deviation lists', 'S18': 'appendix',
    }
    _NAV_LABELS = {
        'S7': 'Coach', 'S1': 'Result',
        'S6': 'KPIs', 'S2': 'Top hands',
        'SIE': 'Issue Explorer', 'S3': 'Leaks (Legacy)', 'S4': 'Tourney type',
        'S8': 'Preflop', 'S9': 'Postflop SRP',
        'S10': 'Postflop 3BP/4BP', 'S11': 'Mechanics',
        'S13': 'Aggression', 'S5': 'Action Items',
        'S12': 'Progress', 'S14': 'QA',
        'S15': 'Raw Stats', 'S16': 'Glossary',
        'S17': 'Deviation', 'S18': 'Appendix',
    }
    doc._nav_sections = []
    # Phase 4.8: Summary (was TL;DR) is now a proper segment (sec-0).
    doc._nav_sections.append(('sec-0', 'Summary', 'executive summary'))
    for label, _fn in section_emitters:
        if want is not None and label not in want:
            continue
        # Map S-label to the section anchor used in the report
        # B-V13: SIE uses a custom anchor, not the generic sec-N pattern
        if label == 'SIE':
            anchor = 'sec-issue-explorer'
        else:
            sec_num = label[1:]  # "S5" -> "5"
            anchor = f"sec-{sec_num}"
        nav_label = _NAV_LABELS.get(label, label)
        subtitle = _NAV_SUBTITLES.get(label, '')
        doc._nav_sections.append((anchor, nav_label, subtitle))

    return doc





def _compute_table_size_breakdown(hands):
    from collections import defaultdict
    by_ts = defaultdict(lambda: {'hands': 0, 'vpip_n': 0, 'pfr_n': 0, 'net_bb': 0.0})
    for h in hands:
        ts = str(h.get('table_size', '?'))
        by_ts[ts]['hands'] += 1
        if h.get('vpip'):
            by_ts[ts]['vpip_n'] += 1
        if h.get('pfr'):
            by_ts[ts]['pfr_n'] += 1
        by_ts[ts]['net_bb'] += h.get('net_bb', 0)
    out = {}
    for ts, d in by_ts.items():
        n = d['hands']
        if n:
            out[ts] = {
                'hands': n,
                'vpip_pct': 100.0 * d['vpip_n'] / n,
                'pfr_pct': 100.0 * d['pfr_n'] / n,
                'net_bb': d['net_bb'],
                'bb_per_100': 100.0 * d['net_bb'] / n,
            }
    return out


# ============================================================
# HEADER + TL;DR + LEGEND
# ============================================================

def _emit_header(doc, s, rd):
    vol = s.get('volume', {})
    n_hands = vol.get('hands', 0)
    n_t = vol.get('tournaments', 0)
    n_b = vol.get('bullets', 0)
    date = vol.get('date', '')
    _player = rd.get('player_name', 'Knockman')
    doc.w(f"# Pokerbot Report — {_player}, {date}")
    # v8.3.0: Renderer version moved to QA metadata (not visible in main body)
    # Batch 2 (#6): compact coverage stats
    _n_total = vol.get('hands', 0)
    _n_eai = len([e for e in (s.get('eai', {}).get('hands', []) or [])
                  if e.get('hero_equity') is not None])
    _n_analyst = len([k for k in (rd.get('analyst_commentary', {}) or {})
                      if not k.startswith('__')])
    _n_appendix = len(rd.get('appendix_hand_ids_all', []) or [])
    doc.w(f"*Coverage:{_new_badge('coverage_stats')} {_n_total} hands · "
          f"{_n_eai} with equity · {_n_analyst} analyst-reviewed · "
          f"{_n_appendix} in appendix*")
    # Skill-context sidebar line (Ron 2026-05-14, build #2). Backward-looking
    # trailing-window logit + AvgF at the session's primary BI tier. Provides
    # "where I stood entering today" orientation — NOT a same-day measurement.
    # Source: rd['skill_context'] (populated by prepare_report_data when
    # per-tournament history is available; renderer is stateless otherwise).
    skill_ctx = rd.get('skill_context')
    if skill_ctx and skill_ctx.get('verdict_line'):
        doc.w(f"*{skill_ctx['verdict_line']}*")
    # ROI forecast sidebar line (Ron 2026-05-14, v7.49.10). Predicts forward
    # 200-bullet ROI from THIS session's metrics using the triangulation-v2
    # regression model. Wide PI reflects MTT variance (~±70% ROI 80% CI).
    roi_fc = rd.get('roi_forecast')
    if roi_fc and roi_fc.get('verdict_line'):
        doc.w(f"*{roi_fc['verdict_line']}*")
    doc.w("")



def generate_report_draft(stats, hands, report_data=None):
    """Back-compat entry point — wraps render_md.

    Existing callers in gem_analyzer.py (line 4807) and
    test_csv_row_complete.py expect this signature and a markdown
    string return. v7.35: returns the I-XIII V4 layout instead of
    the old Del 0/1A/2B/etc. structure.

    Args:
        stats: the stats dict from analyze_session()
        hands: list of hand dicts from the parser
        report_data: pre-staged report_data from gem_report_data.py
                     (optional; falls back to {} if not passed)

    Returns:
        Complete markdown report as a string.
    """
    rd = report_data if report_data is not None else {}
    return render_md(stats, rd, hands)
