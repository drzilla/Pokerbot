"""Section XIV (Appendix) emitter and helpers."""

from gem_report_draft import _state
from gem_report_draft._helpers import (_wilson_ci, _clr, _clr_min, _clr_naive,
    _pctc, _stat_signal, _verdict_ci, _verdict_pct, _hand_ref, _hand_ref_short,
    _xref, _stat_row, _stat_row_pct, _aim_lookup_from_watchlist, _back_to_kpis,
    _compact_range, _run_emoji, _outcome_label, _CI_Z_DEFAULT, _MIN_N_FOR_SIGNAL,
    _RANK_ORD, _break_at_sentences, _href, _render_action_lines, _street_cards,
    _compute_pot_by_street, _emit_correct_ranges, _agg_gate_label, _agg_candidates, _agg_one_label, _agg_commentary,
    _combo_to_chart)
from gem_report_draft._html import (Doc, _card_html, _cards_html,
    _cards_str_to_pills, _cards_text_to_pills, _md_inline, _html_escape,
    _sort_cards_desc, _describe_made_hand, _SUIT_HTML, _RANK_VALUES, _SUIT_VALUES)
from gem_report_draft._hand_grid import (_render_hand_grid_table,
    _key_decision_action_class, _pick_key_action_idx, _hero_actions_by_street_from_app,
    _hero_action_verbs_by_street_from_app, _split_argument_into_notes,
    _verdict_display_label)
from gem_report_draft._helpers import auto_verdict_needs_review

import gem_made_hands as mh
import gem_gtow
# v8.14.1 rev-4 (Blocker C): module-level chart-label helper so every render
# function (deviation-range text, XIV.B flag note, range-check) can humanize raw
# chart ids — it was previously imported only locally inside one function.
from gem_chart_labels import chart_display_label as _cdl

# v7.80: hole-card nickname for the hand-example grid header. Defensive
# import — a missing gem_nicknames module must never break a report render.
try:
    from gem_nicknames import nickname_for
except Exception:
    def nickname_for(cards, path=None):
        return None


# ── v8.13.1 P2: W-POT lint convention fix ──────────────────────────────────
# The analyst convention "call X into Y" quotes Y = the pot AT THE DECISION
# (pot AFTER the villain's bet, BEFORE Hero's call). The old W-POT lint compared
# only against street-START pots and false-flagged correct pot odds (e.g.
# "call 7BB into 19.9BB" warned because the street-start pot was 12.9BB). A
# claim now also passes if it matches a real _pot_odds per-street pot.
def _wpot_pot_figures(pot_odds_block):
    """Every legitimate pot figure an analyst may quote as the 'Y' in
    'call X into Y' — pot-before-call and total-pot, top-level and per-street —
    from the hand's _pot_odds block."""
    figs = set()
    if not isinstance(pot_odds_block, dict):
        return figs
    for k in ('pot_before_call_bb', 'pot_bb', 'total_pot_bb'):
        v = pot_odds_block.get(k)
        if isinstance(v, (int, float)) and v > 0:
            figs.add(round(float(v), 1))
    for ps in (pot_odds_block.get('per_street_calls') or []):
        if isinstance(ps, dict):
            for k in ('pot_before_call_bb', 'total_pot_bb'):
                v = ps.get(k)
                if isinstance(v, (int, float)) and v > 0:
                    figs.add(round(float(v), 1))
    return figs


def _wpot_claim_ok(claimed, pot_odds_block, windows, tol=0.12):
    """A 'call X into Y' pot claim passes if Y matches EITHER a real _pot_odds
    per-street pot (pot-before-call / total) OR a street-start window. This
    stops correct pot-odds phrasing from being flagged just because the figure
    is the at-decision pot rather than the street-start pot."""
    if claimed <= 0:
        return True
    for fig in _wpot_pot_figures(pot_odds_block):
        if fig and abs(claimed - fig) <= max(0.5, fig * tol):
            return True
    for _ws, _wlo, _whi in (windows or []):
        if _wlo * 0.7 <= claimed <= _whi * 1.3:
            return True
    return False


def _street_attr(v):
    """Return a validated street name for data-street attribute, or empty string."""
    s = str(v or '').lower().replace('-', '').replace('_', '').replace(' ', '')
    return s if s in {'preflop', 'flop', 'turn', 'river'} else ''


def _stack_cover_label(hero_chips, villain_chips, bb_chips, tol_bb=0.1):
    """v8.12.12 (Obj-F): cover status of one villain vs Hero, computed from the
    real chip stacks — NOT from upstream seat['hero_covers']/['covers_hero']
    flags, which were only correct for the BB seat (others fell through to a
    flat '= equal'). Compares EVERY seat to Hero and reports direction + delta.

    Returns '✓ Hero covers +X.XBB' when Hero has the larger stack,
    '✗ Villain covers Hero +X.XBB' when the villain does, and '≈ roughly equal'
    only when the two stacks are within ``tol_bb`` big blinds (true near-ties).
    Cover direction drives PKO bounty collectibility, so a wrong '= equal' here
    silently mis-states whether a villain's bounty is even winnable.
    """
    bb = bb_chips or 1
    delta = ((hero_chips or 0) - (villain_chips or 0)) / bb   # +ve => Hero deeper
    if abs(delta) < tol_bb:
        return '≈ roughly equal'
    if delta > 0:
        return f'✓ Hero covers +{delta:.1f}BB'
    return f'✗ Villain covers Hero +{-delta:.1f}BB'


def _pko_bounty_usd(rd, h):
    """v8.12.12 rev-3 (Obj-G): a SAFE per-bounty dollar value for the estimated-
    bounty line, or None. Searches the USD overlay's per-tournament entry for an
    explicit bounty-face dollar amount (``bounty_usd``). Returns None when no
    clean dollar figure exists in the export — the caller then says so rather
    than fabricating one. A chip→$ conversion of the model BB estimate is NOT a
    valid bounty dollar value (MTT chips are not redeemable dollars), so it is
    never synthesised here. Never raises.
    """
    try:
        _tid = h.get('tournament_id') or h.get('tournament') or ''
        _tname = h.get('tournament') or ''
        for _t in ((rd.get('usd_overlay') or {}).get('per_tournament') or []):
            if str(_t.get('tid', '')) == str(_tid) or (
                    _tname and _t.get('name') == _tname):
                _usd = _t.get('bounty_usd')
                if isinstance(_usd, (int, float)) and _usd > 0:
                    return float(_usd)
        return None
    except Exception:
        return None


def _bounty_trust_strip_md(rd, h, _po):
    """v8.14.1 rev-3 (Blocker 1): the compact reconciled "Bounty trust:" strip,
    rendered in the REAL per-hand pot-odds block (XIV.A + XIV.B) for ANY bounty
    hand — NOT gated on the BB-defense pko_context, which never enables for the
    push / call-jam all-ins the user actually flagged (73281442, 73559949).

    Reuses the pure, tested reconcile_pko_trust() so cover / collectibility /
    $ bounty / chip-vs-PKO threshold are reconciled in ONE place; the cover state
    comes from the canonical h['bounty_collectible'] (the same one-source-of-truth
    fact the analyzer's "bounty covers villain" flag and the coaching card use),
    so the strip can never contradict them. When no chip-vs-PKO threshold was
    modelled, the strip says so explicitly rather than implying a silent verdict.
    Returns '' for non-bounty hands or when there is nothing concrete to say.
    """
    _po = _po or {}
    _fmt = h.get('format', '')
    _bnt = _po.get('bounty') or {}
    _bv = _bnt.get('value_bb') or h.get('bounty_value_bb') or 0
    _collect = h.get('bounty_collectible')
    if _fmt != 'BOUNTY' and not _bv and _collect not in ('collectible', 'not_collectible'):
        return ''
    try:
        from gem_pko_research import reconcile_pko_trust
    except Exception:
        return ''
    _cover_bucket = {'collectible': 'Hero covers',
                     'not_collectible': 'Hero covered'}.get(_collect, '')
    _can_collect = (True if _collect == 'collectible'
                    else False if _collect == 'not_collectible' else None)
    _vpos = h.get('jammer_position') or ''
    if _collect == 'collectible':
        _cover_label = (f'Hero covers the {_vpos}; bounty collectible' if _vpos
                        else 'Hero covers the villain; bounty collectible')
    elif _collect == 'not_collectible':
        _cover_label = (f'{_vpos} covers Hero; bounty not collectible' if _vpos
                        else 'Villain covers Hero; bounty not collectible')
    else:
        _cover_label = ''
    _n_sd = _po.get('n_players_at_showdown') or 2
    try:
        _tr = reconcile_pko_trust(
            coverage_bucket=_cover_bucket,
            can_collect_bounty=_can_collect,
            players=_n_sd,
            coverage_label=_cover_label,
            bounty_value_bb=_bv,
            bounty_usd=_pko_bounty_usd(rd, h),
            discount_pp=_bnt.get('discount_pp', 0) or 0,
            chip_threshold_pct=_po.get('required_eq_pct'),
            pko_threshold_pct=_po.get('required_eq_bounty_pct'),
            overjam_bb=None)
    except Exception:
        return ''
    if not _tr.get('trust_line'):
        return ''
    _prefix = '⚠️ ' if _tr.get('contradiction') else '\U0001f3af '
    return _prefix + '**Bounty trust:** ' + _tr['trust_line']


_SIGNAL_LABELS_RENDER = {
    'open_limp': 'Open Limp', 'limp_call': 'Limp-Call',
    'weak_showdown_call': 'Weak Showdown Call',
    'passive_aggro_pivot': 'Passive → Aggro Pivot',
    'repeated_blind_overfold': 'Repeated Blind Overfold',
    'multiway_donk': 'Multiway Donk', 'weird_minbet': 'Weird Min-Bet',
    'cold_call_3bet_oop': 'Cold-Call 3-Bet OOP',
    'river_bluff_shown': 'River Bluff Shown',
    'calldown_weak_pair': 'Call-Down Weak Pair',
}

def _emit_gtow_button(doc, hand, app_details, hid_short, rd=None):
    """Emit the GTOW button for one hand-detail-card.

    v2.0: Always ON (no longer gated behind rd['gtow_links']).
    URL builder uses validated GTOW reference data.
    Button placed at top-right of the hand card via CSS absolute positioning.

    Statuses:
      ready       -> '⚡GTOW' (dark button, clickable)
      partial     -> '⚡GTOW' (amber tint, clickable, links to preflop root)
      unavailable -> no button emitted (silent — don't clutter the card)
    """
    schema = gem_gtow.build_gtow_schema(hand, app_details)
    if schema['status'] == 'unavailable' or not schema.get('url'):
        return
    _url = _html_escape(schema['url'])
    _tip = _html_escape(schema.get('spot_summary', ''))
    _cls = 'gtow-btn'
    if schema['status'] == 'partial':
        _cls += ' approximate'
    # v8.12.0a: honor the builder's honesty label — bounty hands served a
    # ChipEV regime show 'GTOW≈' (gem_gtow v2.2.0), not a plain 'GTOW'.
    _btn_txt = 'GTOW≈' if '≈' in (schema.get('label') or '') else 'GTOW'
    doc.w(f"<a class='{_cls}' "
          f"data-hand-id='{hid_short}' "
          f"href='{_url}' "  # R2: data-gtow-url dropped (dup of href; ~138KB/report). Verification passes read .gtow-btn[href].

          f"target='_blank' rel='noopener noreferrer' "
          f"title='{_tip}'>"
          f"<span class='gtow-flash'>⚡</span>{_btn_txt}</a>")


def _bold_hand_in_range(range_str, hand_class):
    """B173 (Ron 2026-05-24): bold the slice of a comma-separated opening-range
    string that covers Hero's hand-class, so a Missed-Steal note shows at a
    glance WHERE the folded hand sits — e.g. JTo is well inside the CO open
    range, not at its bottom. Exact-token match first; falls back to a
    '+'-notation token that covers the hand (same top rank + suitedness, or a
    pair threshold). No-op if nothing matches."""
    if not range_str or not hand_class:
        return range_str
    hc = hand_class.strip()
    _RANKS = '23456789TJQKA'

    def _ri(r):
        return _RANKS.index(r) if r in _RANKS else -1

    def _covers(tok):
        tok = tok.strip()
        if tok == hc:
            return True
        if not tok.endswith('+'):
            return False
        base = tok[:-1]
        # pair threshold, e.g. '77+'
        if (len(base) == 2 and base[0] == base[1]
                and len(hc) == 2 and hc[0] == hc[1]):
            return _ri(hc[0]) >= _ri(base[0])
        # XYs+ / XYo+ — same top rank and suitedness, kicker at or above
        if (len(base) == 3 and len(hc) == 3
                and base[2] == hc[2] and base[0] == hc[0]):
            return _ri(hc[1]) >= _ri(base[1])
        return False

    out, done = [], False
    for p in [p.strip() for p in range_str.split(',')]:
        if not done and _covers(p):
            # B174 (Ron 2026-05-25): emit <strong> not markdown ** — this string
            # lands inside a raw-HTML <p> block in the analyst-notes div, where
            # the markdown converter does NOT process inline ** (it leaked as
            # literal '**A5o+**' in Missed-Steal notes). HTML renders in both
            # the .html build and any markdown viewer of the .md.
            out.append(f"<strong>{p}</strong>")
            done = True
        else:
            out.append(p)
    return ', '.join(out)


def _emit_agg_gate_block(doc, hid, rd, hand=None):
    """B173 (Ron 2026-05-24): render aggression-gate commentary INSIDE a yellow
    analyst-notes block, placed below the hand grid.

    Enhanced: includes per-street draw profile context so the reader sees
    what Hero held on the flagged street (e.g. "FLOP: set of As").
    v8.11.0c: groups candidates by street with street headers matching the
    hand-grid style, so commentary appears under the correct street."""
    cands = _agg_candidates(hid, rd)
    _scn = _solver_confirm_note(hid, rd)
    if not cands and not _scn:
        return

    _street_labels = {'preflop': 'PRE-FLOP', 'flop': 'FLOP',
                      'turn': 'TURN', 'river': 'RIVER'}
    _street_order = ('preflop', 'flop', 'turn', 'river')

    by_street = {}
    for _ac in cands:
        _st = (_ac.get('street_of_interest') or '').lower()
        if _st not in _street_labels:
            _st = 'river'
        by_street.setdefault(_st, []).append(_ac)

    doc.w("<div class='analyst-notes'>")
    for _st in _street_order:
        _items = by_street.get(_st, [])
        if not _items and not (_scn and _st == 'river'):
            continue
        doc.w(f"<p class='note-street'><strong>{_street_labels[_st]}</strong></p>")
        for _ac in _items:
            _ae, _al = _agg_one_label(_ac)
            _street_ctx = ''
            _ac_street = _ac.get('street_of_interest', '')
            if hand and _ac_street:
                try:
                    from gem_made_hands import draw_profile as _dp_agg
                    _board = hand.get('board') or []
                    _cards = hand.get('cards') or []
                    _n = {'flop': 3, 'turn': 4, 'river': 5}.get(_ac_street, 0)
                    if len(_cards) == 2 and len(_board) >= _n and _n > 0:
                        _dp = _dp_agg(_cards, _board[:_n])
                        # v8.12.8 QA: this paragraph is emitted as RAW HTML,
                        # so markdown ** stayed literal on screen (28 hits in
                        # the 06-11 report) — use <strong> directly. And the
                        # engine-degraded sentinel ("phevaluator unavailable
                        # or insufficient board") is diagnostics, not prose —
                        # never show it to the player.
                        if (_dp and _dp.get('summary')
                                and 'unavailable' not in _dp['summary']):
                            _street_ctx = (f" <strong>{_ac_street.upper()}: "
                                           f"{_dp['summary']}.</strong>")
                except Exception:
                    pass
            doc.w(f"<p>{_ae} <strong>{_al}</strong>{_street_ctx}</p>")
            doc.w(f"<p class='note-cont'>{_agg_commentary(_ac)}</p>")
        if _scn and _st == 'river':
            doc.w(f"<p>{_scn}</p>")
    doc.w("</div>")
    doc.w("")


def _eai_one_liner(s):
    eai = s.get('eai', {})
    # v8.12.4 (QA item 4): prefer the equity-weighted expectation from
    # eai_ev_adjusted — the SAME basis the S1.4 all-ins table total uses.
    # The old hardcoded category multipliers (0.8/0.55/0.2 …) produced a
    # different expected-wins figure than the table (42.9 vs 39.1 on the
    # same 75 spots), so the header said -1.9 while the table said +1.9.
    _adj = s.get('eai_ev_adjusted', {}) or {}
    _adj_exp = sum((_adj.get(k, {}) or {}).get('expected_wins', 0)
                   for k in ('preflop', 'postflop'))
    _adj_act = sum((_adj.get(k, {}) or {}).get('actual_wins', 0)
                   for k in ('preflop', 'postflop'))
    if _adj_exp > 0:
        expected, actual = _adj_exp, _adj_act
    else:
        expected = sum(eai.get('preflop', {}).get(c, {}).get('count', 0) * mult
                       for c, mult in [('ahead', 0.8), ('flip', 0.55), ('behind', 0.2)])
        expected += sum(eai.get('postflop', {}).get(c, {}).get('count', 0) * mult
                        for c, mult in [('ahead', 0.85), ('flip', 0.5), ('behind', 0.25)])
        actual = sum(eai.get('preflop', {}).get(c, {}).get('won', 0)
                     for c in ['ahead', 'flip', 'behind'])
        actual += sum(eai.get('postflop', {}).get(c, {}).get('won', 0)
                      for c in ['ahead', 'flip', 'behind'])
    delta = actual - expected
    # B68 (v7.49, Ron 2026-05-12): add percentage form. "EAI -2.2 vs expected
    # 9.7" is harder to interpret than "-22% vs expected" — Ron asked for both.
    pct = (100.0 * delta / expected) if expected > 0 else 0
    pct_str = f"{pct:+.0f}%" if expected > 0 else "n/a"
    if abs(delta) < 1:
        return f"👍 All-Ins roughly expected ({actual:.1f}/{expected:.1f}, {pct_str})"
    if abs(delta) < 2:
        return f"🟡 All-Ins {delta:+.1f} vs expected ({actual:.1f}/{expected:.1f}, {pct_str})"
    return f"🔴 All-Ins {delta:+.1f} vs expected ({actual:.1f}/{expected:.1f}, {pct_str})"


def _per_tourney_one_liner(pnl):
    if not pnl:
        return "—"
    deep = sum(1 for p in pnl if p['net_bb'] > 100)
    bust = sum(1 for p in pnl if p['net_bb'] < -50)
    if deep > 0 and bust > 0:
        return f"bimodal — {deep} deep run(s), {bust} early bust(s)"
    if deep > 0:
        return f"{deep} deep run(s) carried the session"
    if bust > 0:
        return f"{bust} bust(s) drove the deficit"
    return "modest moves across the field"


def _short_tournament(name, max_len=50):
    if not name:
        return "—"
    return name[:max_len] + ("…" if len(name) > max_len else "")


def _bust_verdict(h):
    cards = ''.join(h.get('cards', []))
    asum = h.get('action_summary', '')
    if 'allin' in str(h.get('pf_action','')).lower() or h.get('pf_allin'):
        return "PF AI — verify equity vs jam range"
    if 'xr-ai' in asum:
        return "🟡 turn x/r AI — read-dependent review"
    if 'callAI' in asum:
        return "🟡 called AI — pot-odds vs range check"
    if h.get('went_to_sd'):
        return "saw SD — see cooler / read-dependent review"
    return "see line"


def _generate_cheat_sheet(s, rd, hands):
    drills = []
    core = s.get('core', {})
    cb = s.get('cbet', {})

    # Caller IP passivity
    cipa = core.get('caller_ip_flop_agg', 0)
    cipa_n = core.get('caller_ip_flop_n', 0)
    if cipa_n >= 5 and cipa < 30:
        drills.append("When IP villain checks the flop to me, BET small (33-50%) by default. "
                      "Range advantage + position wins the pot most of the time.")

    # SB defense
    sb = s.get('facing_action', {}).get('sb_defense_vs_lp', {})
    sb_opps = sb.get('opps', 0)
    sb_count = sb.get('count', 0)
    if sb_opps >= 8:
        sb_pct = 100.0 * sb_count / sb_opps
        if sb_pct < 30:
            drills.append("vs CO/BTN open from SB, my call+3bet rate should be 30-40%. "
                          "I'm folding too much — defend wider with suited Ax, 8x+ broadways.")

    # HU IP cbet auto-pilot
    hu_ip = cb.get('hu_ip_pct', 0)
    hu_ip_n = cb.get('hu_ip_opp', 0)
    if hu_ip_n >= 10 and hu_ip > 80:
        drills.append("HU IP c-bet is auto-piloting at " + f"{hu_ip:.0f}%. "
                      "Slow down on wet textures (low_ragged, broadway_coordinated, monotone) — "
                      "those want ~50-60% frequency, not 90%+.")

    # Turn x/r reads (recurring lesson from this session)
    drills.append("When a flat-caller raises me on turn, default to bluff-catcher zone. "
                  "Two pair, TPTK, TPGK = call/fold range. Re-raise only with 2P+ that has "
                  "redraws or the actual nuts.")

    # Pre-session mantra
    drills.append("**Pre-session mantra:** name the population frequency being exploited "
                  "BEFORE any non-standard river action.")

    # Bust hand framing
    drills.append("**Bust hand framing:** the real strategic question is what happened "
                  "1-2 decisions BEFORE the all-in, not the showdown card.")

    if not drills:
        drills.append("No top-line drills surfaced this session. Continue current process discipline.")
    return drills


def _street_from_text(txt):
    """Best-effort street inference from a detector/flag label string."""
    t = (txt or '').lower()
    if 'river' in t: return 'river'
    if 'turn' in t:  return 'turn'
    if 'flop' in t:  return 'flop'
    if any(k in t for k in ('preflop', 'pre-flop', 'steal', ' open', 'defend',
                             '3-bet', '3bet', '4-bet', '4bet', 'iso', 'squeeze')):
        return 'preflop'
    return None


def _embolden_hand_in_range(compact, hs):
    """v8.12.8 QA3 (66313101/65698103): bold the range token that contains
    Hero's hand so the reader sees WHERE it sits (J6o inside 'J6o+').
    Handles exact tokens, 'Xy+' families, pairs '22+' and spans 'A5s-A2s'.
    Markdown bold — every consumer path runs inline-md."""
    if not hs or not compact:
        return compact
    import re as _re
    _RV = {r: i for i, r in enumerate('23456789TJQKA', 2)}

    def _covers(tok):
        tok = tok.strip()
        if tok == hs:
            return True
        if len(hs) == 2:                                   # pair like 'QQ'
            m = _re.match(r'^([2-9TJQKA])\1\+$', tok)
            return bool(m and _RV.get(hs[0], 0) >= _RV.get(tok[0], 0))
        if len(hs) != 3:
            return False
        m = _re.match(r'^([2-9TJQKA])([2-9TJQKA])([so])\+$', tok)
        if m and hs[2] == m.group(3) and hs[0] == m.group(1):
            return _RV.get(hs[1], 0) >= _RV.get(m.group(2), 0)
        m = _re.match(r'^([2-9TJQKA])([2-9TJQKA])([so])-'
                      r'([2-9TJQKA])([2-9TJQKA])([so])$', tok)
        if (m and hs[2] == m.group(3) == m.group(6)
                and hs[0] == m.group(1) == m.group(4)):
            lo, hi = sorted((_RV.get(m.group(2), 0), _RV.get(m.group(5), 0)))
            return lo <= _RV.get(hs[1], 0) <= hi
        return False

    def _sub(m):
        tok = m.group(0)
        return f'**{tok}**' if _covers(tok) else tok

    return _re.sub(r'[2-9TJQKA]{2}[so]?(?:\+|-[2-9TJQKA]{2}[so]?)?',
                   _sub, compact)


def _canon_supersede(h):
    """v8.14.1 REV3 (Blocker 2, hand 72807590): when the chart-backed canonical
    "Range evidence" block renders for hand ``h``, IT is the single source of
    truth for preflop chart membership (correct seat + IN/OUTSIDE, proxy/closest
    disclosed). The legacy per-deviation "Correct range — {chart}" prose derives
    its chart from the detector's STORED position, which applies a short-table
    adjustment (e.g. 7-max MP opens off the HJ chart, _open_chart_pos) that the
    canonical block does not — so the two can disagree (97s read "inside HJ" by
    the legacy line vs "OUTSIDE the MP open" by the canonical block). Callers
    defer to the canonical block to avoid a second, position-divergent claim.
    Returns (present, membership, hero_hand, chart_label)."""
    if not isinstance(h, dict):
        return (False, None, None, None)
    try:
        from gem_report_draft._helpers import hand_range_evidence as _hre_cs
        ev = _hre_cs(h)
        if ev and ev.get('chart_key'):
            return (True, ev.get('membership'), ev.get('hero_hand'),
                    _cdl(ev.get('chart_key')))
    except Exception:
        pass
    return (False, None, None, None)


def _deviation_range_text(hid, s, h=None):
    """Look up the correct range for a hand's preflop deviation from
    s['preflop_deviations']. For punts/mistakes promoted from deviations,
    this surfaces the acceptable chart or iso-range so the hand detail card
    shows WHAT the correct range is (B-RANGE, Ron 2026-05-30).
    Returns text to append to explanation, or ''.

    v8.14.1 REV3: when the canonical Range-evidence block renders for ``h`` the
    legacy chart line is suppressed (it is authoritative); if that block says
    OUTSIDE while the detector flagged a "Missed" deviation (short-table chart
    divergence), a reconciliation note defers to the strict positional chart
    instead of asserting "inside this chart — passing on it is the deviation"."""
    for d in (s.get('preflop_deviations', []) or []):
        if not isinstance(d, dict) or d.get('id') != hid:
            continue
        # Chart-based range (Wide Open, Wide 3-Bet, Wide BB Defend, etc.)
        _chart = d.get('chart')
        _dev_charts = s.get('_dev_charts') or {}
        if _chart and _dev_charts.get(_chart):
            _cs_present, _cs_mem, _cs_hand, _cs_lbl = _canon_supersede(h)
            if _cs_present:
                _tl = (d.get('type') or '').lower()
                if _cs_mem == 'outside' and 'missed' in _tl:
                    return (f" Against the charted {_cs_lbl} range, "
                            f"{d.get('cards', 'this hand')} is outside — a "
                            f"table-size-dependent marginal, not a clear leak.")
                return ''
            _combos = _dev_charts[_chart]
            _tl = (d.get('type') or '').lower()
            if 'wide' in _tl:
                _vd = (f"{d.get('cards', 'this hand')} is wider than this "
                       "chart — the open itself is the deviation")
            elif 'missed' in _tl:
                _vd = (f"{d.get('cards', 'this hand')} is inside this "
                       "chart — passing on it is the deviation")
            else:
                _vd = f"compare {d.get('cards', 'this hand')} to this chart"
            # v8.12.8 QA3: bold the token Hero's hand falls under
            _rng_txt = _embolden_hand_in_range(
                _compact_range(_combos), d.get('cards', ''))
            # v8.14.1 rev-4 (Blocker C): show the human chart label, not the raw
            # id (e.g. "SB re-jam vs CO open", not REJAM_SBvsCO).
            return (f" Correct range — {_cdl(_chart)} ({len(_combos)} hand classes): "
                    f"{_rng_txt}. {_vd}.")
        # Inline iso_range (CVJ/Iso-Jam threshold)
        if d.get('iso_range'):
            _ir = d['iso_range']
            _tl = (d.get('type') or '').lower()
            if 'iso' in _tl:
                _lbl = 'Acceptable iso-jam range'
            else:
                _lbl = 'Acceptable call range vs jam'
            return (f" {_lbl} for this spot ({len(_ir)} hand classes): "
                    f"{_compact_range(_ir)}. "
                    f"{d.get('cards', 'this hand')} is outside this range.")
    return ''


def _xivb_flag_note(hid, s, rd, h=None):
    """B128 (Ron 2026-05-20): structured 'why-flagged' info for a XIV.B hand.
    Every hand that earns an appendix example was flagged by something — and
    Ron wants that comment to follow the SAME structure as XIV.A: a verdict-
    style line + a numbered note in the yellow analyst-notes block with a (N)
    pill on the relevant action. Returns a dict or None:
      {emoji, label, explanation, street}
        emoji/label  -> the '*Flagged:*' line
        explanation  -> prose fed to _split_argument_into_notes (the note body)
        street       -> which street's Hero action carries the (N) pill
    Sourced from the rule / detector / overlay that flagged the hand."""
    # MDA population overlay — preflop exploit decisions
    for kind in ('missed', 'aligned'):
        for ex in (s.get('mda_exploits', {}) or {}).get(kind, []) or []:
            if not isinstance(ex, dict) or ex.get('hand_id') != hid:
                continue
            ha = ex.get('hero_action') or '?'
            ma = ex.get('mda_action') or '?'
            rec = ex.get('mda_rec_id') or 'MDA'
            rng = ex.get('ev_bb_range') or []
            ev = ex.get('ev_bb')
            if isinstance(rng, (list, tuple)) and len(rng) == 2:
                ev_str = (f", estimated {ev:+.1f} BB (range {rng[0]:+.0f} to {rng[1]:+.0f})"
                          if ev is not None
                          else f", estimated {rng[0]:+.0f} to {rng[1]:+.0f} BB")
            else:
                ev_str = ''
            if kind == 'missed':
                # Item 15: guard against tautological wording when hero_action
                # and mda_action are the same family (e.g. rejam \u2248 jam).
                _ha_norm = ha.lower().replace('-', '').replace(' ', '')
                _ma_norm = ma.lower().replace('-', '').replace(' ', '')
                if _ha_norm == _ma_norm or _ma_norm in _ha_norm or _ha_norm in _ma_norm:
                    _expl = (f"Preflop, Hero chose to {ha}{ev_str}. MDA flags this "
                             f"as a population exploit ({rec}), but Hero's action "
                             f"already matches the recommendation \u2014 reviewing "
                             f"whether the flag is a false positive.")
                else:
                    _expl = (f"Preflop, Hero chose to {ha}; MDA recommends "
                             f"<strong>{ma}</strong> instead{ev_str} \u2014 a population-derived "
                             f"exploit, not a GTO-chart deviation.")
                return {'emoji': '\U0001F7E1', 'label': f'MDA exploit missed ({rec})',
                        'street': 'preflop',
                        'explanation': _expl}
            return {'emoji': '\U0001F7E2', 'label': f'MDA-aligned ({rec})',
                    'street': 'preflop',
                    'explanation': (f"Preflop, Hero chose to {ha}, matching the "
                                    f"population-exploit line \u2014 kept for reference.")}
    # Auto-detected punts
    for p in ((s.get('punts', {}) or {}).get('hands', []) or []):
        if isinstance(p, dict) and p.get('id') == hid:
            note = (p.get('note') or 'Flagged as a punt by the detector').rstrip('.')
            # B-RANGE (Ron 2026-05-30): append correct range from the
            # underlying deviation so the punt card shows what Hero
            # should have done (like Wide/Missed Open already does).
            expl = note + '.' + _deviation_range_text(hid, s, h)
            return {'emoji': '\U0001F534', 'label': p.get('type', 'Punt'),
                    'street': (p.get('street') or '').lower() or _street_from_text(p.get('type')),
                    'explanation': expl}
    # Detector mistakes
    for m in (s.get('mistakes', []) or []):
        if isinstance(m, dict) and m.get('id') == hid:
            t = m.get('type', 'Flagged')
            asum = (m.get('action_summary') or '').rstrip('.')
            expl = (t + '. ' + asum).strip().rstrip('.') + '.'
            # B159 (Ron 2026-05-23): feedback loop — when the flag is a
            # missed open/steal, append the correct opening range and which
            # tier the folded hand sits in, so the XIV.B note tells Ron what
            # he SHOULD have done, not just that he missed something.
            if m.get('open_range_core'):
                tier = (m.get('range_tier') or '').upper()
                cards_lbl = m.get('cards', 'this hand')
                # B189 (Ron 2026-05-25): a CORE hand demoted to MARGINAL by the
                # 8-max+ / short-stack rule must NOT read "a clear open; folding
                # is the leak" — that contradicts the MARGINAL flag. Key the
                # verdict sentence off the final confidence, not the raw tier.
                if tier == 'CORE' and m.get('tier_demoted'):
                    _reason = m.get('demotion_reason') or 'table/stack context'
                    if 'bottom of the' in _reason and 'open range' in _reason:
                        # B206/B207: core-fringe — a property of the hand.
                        tier_verdict = (f"{cards_lbl} sits at the {_reason} — "
                                        f"a low-playability open. It is a "
                                        f"marginal open; folding it is "
                                        f"defensible, not a clear leak")
                    else:
                        tier_verdict = (f"{cards_lbl} is a CORE open at 6-max, "
                                        f"but demoted to a marginal open here "
                                        f"({_reason}) — folding it is "
                                        f"defensible, not a clear leak")
                elif tier == 'CORE':
                    tier_verdict = (f"{cards_lbl} is in the CORE tier — a clear "
                                    "open; folding it is the leak")
                elif tier == 'EXTENDED':
                    tier_verdict = (f"{cards_lbl} is in the EXTENDED tier — a "
                                    "marginal bottom-of-range open; folding it "
                                    "is defensible")
                else:
                    tier_verdict = (f"{cards_lbl} sits in the {tier} tier"
                                    if tier else '')
                expl += (f" Correct opening range — CORE (clear opens): "
                         f"{_bold_hand_in_range(m['open_range_core'], m.get('cards',''))}.")
                if m.get('open_range_extended'):
                    expl += (f" EXTENDED (marginal adds): "
                             f"{_bold_hand_in_range(m['open_range_extended'], m.get('cards',''))}.")
                if tier_verdict:
                    expl += f" {tier_verdict}."
            # Item 14: for Missed Push / Reshove, show the push/fold range
            # so the hand description says WHAT range the fold was judged
            # against (per Analyst_Writing_Checklist §3b).
            if m.get('push_range') and ('Push' in t or 'Reshove' in t):
                _pr = m['push_range']
                _icm = m.get('icm_note', '')
                expl += (f" Nash push range at {m.get('pos','?')} "
                         f"{m.get('stack_bb',0)}BB: **{_pr}**."
                         f"{(' ' + _icm.strip()) if _icm else ''}")
            # B175 (Ron 2026-05-25): for CVJ / re-jam-over-jam flags, surface
            # the villain jam range + Hero's equity vs it. The analyzer puts
            # the clause in m['note'] after a "| Villain ..." marker; lift it
            # into the appendix note so Ron sees what was called, vs what,
            # at what price - not just "outside threshold".
            if ('CVJ' in t or 'Iso-Jam' in t) and m.get('note'):
                _ci = m['note'].find('| Villain ')
                if _ci != -1:
                    expl = expl.rstrip('.') + '. ' + m['note'][_ci + 2:].strip() + '.'
            # B-RANGE (Ron 2026-05-30): append correct chart/iso range for
            # detector-flagged deviations so the hand card shows what range
            # Hero deviated from. Skip when open_range_core already renders
            # range info (Missed Steal path, lines above).
            if not m.get('open_range_core'):
                expl += _deviation_range_text(hid, s, h)
            return {'emoji': '\U0001F7E1', 'label': t,
                    'street': _street_from_text(t),
                    'explanation': expl}
    # Preflop chart deviations
    for d in (s.get('preflop_deviations', []) or []):
        if isinstance(d, dict) and d.get('id') == hid:
            t = d.get('type', 'Preflop deviation')
            conf = d.get('confidence', '')
            # v8.8.6 S1-fix: satellite caveat on confidence label
            _d_fmt_xiv = (d.get('format') or '').upper()
            if _d_fmt_xiv == 'SATELLITE' and conf == 'CLEAR':
                conf = 'CLEAR chipEV-only · SAT/ICM caveat'
            asum = (d.get('action_summary') or '').rstrip('.')
            expl = ('Preflop. ' + t + '. ' + asum).strip().rstrip('.') + '.'
            # B159 (Ron 2026-05-23): append the correct chart range so the
            # note closes the feedback loop — what the range actually is and
            # whether Hero's hand belongs in it.
            _chart = d.get('chart')
            _dev_charts = s.get('_dev_charts') or {}
            if _chart and _dev_charts.get(_chart):
                # v8.14.1 REV3 (Blocker 2): defer to the canonical Range-evidence
                # block when present — do not emit a second, position-divergent
                # "Correct range" line (97s "inside HJ" vs "OUTSIDE MP", 72807590).
                _cs_present, _cs_mem, _cs_hand, _cs_lbl = _canon_supersede(h)
                if _cs_present:
                    if _cs_mem == 'outside' and 'missed' in t.lower():
                        expl += (f" Against the charted {_cs_lbl} range, "
                                 f"{d.get('cards','this hand')} is outside — a "
                                 f"table-size-dependent marginal, not a clear leak.")
                else:
                    _combos = _dev_charts.get(_chart) or []
                    _tl = t.lower()
                    if 'wide' in _tl:
                        _vd = (f"{d.get('cards','this hand')} is wider than this "
                               "chart — the open itself is the deviation")
                    elif 'missed' in _tl:
                        _vd = (f"{d.get('cards','this hand')} is inside this "
                               "chart — passing on it is the deviation")
                    else:
                        _vd = f"compare {d.get('cards','this hand')} to this chart"
                    # v8.12.8 QA3: bold the token Hero's hand falls under
                    _rng_txt_b = _embolden_hand_in_range(
                        _compact_range(_combos), d.get('cards', ''))
                    expl += (f" Correct range — {_cdl(_chart)} ({len(_combos)} hand "
                             f"classes): {_rng_txt_b}. {_vd}.")
            return {'emoji': '\U0001F7E1',
                    'label': t + (f' ({conf})' if conf else ''),
                    'street': 'preflop', 'explanation': expl}
    # Coolers
    cooler_src = rd.get('coolers') or (s.get('coolers', {}) or {}).get('hands', []) or []
    for c in cooler_src:
        cid = c.get('id') if isinstance(c, dict) else (c if isinstance(c, str) else None)
        if cid == hid:
            return {'emoji': '\U0001F7E6', 'label': 'Cooler',
                    'street': c.get('street') if isinstance(c, dict) else None,
                    'explanation': ("A standard stack-off that ran into the top of "
                                    "villain's range \u2014 not a leak, kept for the "
                                    "variance audit.")}
    # B201 (Ron review 2026-05-25, asked twice): when a hand's ONLY flag is an
    # aggression review (no punt/mistake/MDA/cooler above), return it as the
    # flag so its commentary is pinned to the relevant street's Hero action via
    # the numbered-note mechanism — flop note on the flop row, river note on
    # the river row — instead of a disconnected block below the grid.
    _aggc = _agg_candidates(hid, rd)
    if len(_aggc) == 1:
        _ac = _aggc[0]
        _emoji, _label = _agg_one_label(_ac)
        _st = (_ac.get('street_of_interest') or 'flop').strip().lower()
        return {'emoji': _emoji or '\U0001F7E1', 'label': _label or 'Aggression review',
                'street': _st, 'explanation': _agg_commentary(_ac), '_agg': True}
    # B228 (Ron 2026-06-01): blind-spot audit hands — no detector fired, but
    # the analyst must review them the same as any flagged hand.
    _bsa_ids = {e.get('id') for e in
                ((s.get('blindspot_audit') or {}).get('sampled') or [])
                if isinstance(e, dict)}
    if hid in _bsa_ids:
        return {'emoji': '\U0001F50D', 'label': 'Blind-Spot Audit',
                'street': None,
                'explanation': ("No detector flagged this hand — it was randomly "
                                "sampled from un-flagged VPIP hands to check for "
                                "leaks the coded heuristics miss. Review whether "
                                "the play is correct or a new leak pattern.")}
    return None


def _compute_per_tourney_pnl(hands, buyin_breakdown=None):
    """Group hands by tournament. Buyin/bullets looked up from buyin_breakdown
    (in report_data); net BB / bb/100 computed inline from hands."""
    from collections import defaultdict
    bb_lookup = {}
    if buyin_breakdown:
        for b in buyin_breakdown:
            bb_lookup[b.get('tournament','')] = b
    by_t = defaultdict(lambda: {'hands': 0, 'net_bb': 0.0,
                                 'date': '', 'format': '', 'tournament_id': ''})
    _files_by_tourney = defaultdict(set)
    for h in hands:
        t = h.get('tournament', 'UNKNOWN')
        d = by_t[t]
        d['hands'] += 1
        d['net_bb'] += h.get('net_bb', 0)
        if not d['date']:
            d['date'] = h.get('date', '')
        if not d['format']:
            d['format'] = h.get('format', '')
        _fn = h.get('filename', '')
        if _fn:
            _files_by_tourney[t].add(_fn)
        # B228 (Ron 2026-05-25): capture the tournament_id so the I.1 USD
        # join can key off it instead of fuzzy name-matching (GG summary
        # names use ": $" punctuation the HH names don't, so the substring
        # match was silently failing and $Net/ROI showed "—").
        if not d['tournament_id']:
            d['tournament_id'] = str(h.get('tournament_id', '') or '')
    out = []
    for t, d in by_t.items():
        bb100 = (100.0 * d['net_bb'] / d['hands']) if d['hands'] else 0
        bb_info = bb_lookup.get(t, {})
        out.append({
            'tournament': t,
            'tournament_id': d['tournament_id'],
            'buyin': bb_info.get('buyin', 0),
            'bullets': len(_files_by_tourney.get(t, set())) or bb_info.get('bullets', 1),
            'hands': d['hands'],
            'net_bb': d['net_bb'],
            'bb_per_100': bb100,
            'date': d['date'],
            'format': d['format'],
        })
    return sorted(out, key=lambda x: x['net_bb'])


def _tourney_narrative(hands, eai_hands=None, buyin_breakdown=None):
    """B-V10 FEATURE: per-tournament one-liner explaining the result.
    Returns dict[tournament_name] → narrative string.

    Looks at: exit hand (last hand), all-in results, card quality in the
    last stretch, biggest pots, and stack trajectory to produce a human-
    readable summary like "Lost AK vs QQ flip at 15BB" or "card dead,
    blinded down". For multi-bullet tournaments, mentions bullet count."""
    from collections import defaultdict
    PREMIUMS = {'AA','KK','QQ','JJ','AKs','AKo'}
    STRONG = {'TT','99','AQs','AQo','AJs','KQs'}

    # Look up bullet counts from buyin breakdown
    _bullets_by_name = {}
    for b in (buyin_breakdown or []):
        _bullets_by_name[b.get('tournament', '')] = b.get('bullets', 1)

    by_t = defaultdict(list)
    for h in hands:
        by_t[h.get('tournament', 'UNKNOWN')].append(h)

    eai_by_id = {}
    for e in (eai_hands or []):
        eai_by_id[e.get('id', '')] = e

    narratives = {}
    for tname, t_hands in by_t.items():
        # Sort by hand sequence (id is chronological in GG)
        t_hands.sort(key=lambda h: h.get('id', ''))
        n = len(t_hands)
        net = sum(h.get('net_bb', 0) for h in t_hands)
        parts = []

        # 0. Multi-bullet prefix
        _n_bullets = _bullets_by_name.get(tname, 1)
        if _n_bullets > 1:
            parts.append(f"{_n_bullets} bullets")

        # 1. Exit hand analysis (last hand of the tournament)
        last = t_hands[-1]
        last_id = last.get('id', '')
        last_net = last.get('net_bb', 0)
        last_eai = eai_by_id.get(last_id)
        last_stack = last.get('stack_bb', 0) or 0
        last_cards = last.get('cards', [])

        if last_eai and last_eai.get('hero_equity') is not None:
            eq = last_eai['hero_equity']
            # Normalize: EAI equity may be 0-1 fraction or 0-100 percent
            eq_pct = eq * 100.0 if eq <= 1.5 else eq
            _suckout = last_eai.get('suckout', '')
            _won_last = last.get('won')
            if eq_pct >= 55:
                if _won_last:
                    parts.append(f"ahead at {eq_pct:.0f}%")
                elif _suckout == 'hero_got_sucked_out':
                    parts.append(f"suckout ({eq_pct:.0f}% favorite, lost)")
                else:
                    parts.append(f"busted as {eq_pct:.0f}% favorite")
            elif eq_pct >= 42:
                parts.append(f"lost flip ({eq_pct:.0f}%)")
            elif eq_pct > 0:
                if _won_last:
                    parts.append(f"got lucky ({eq_pct:.0f}% underdog, won)")
                else:
                    parts.append(f"behind ({eq_pct:.0f}%)")
            # eq_pct == 0: genuinely drawing dead or equity=None fallback
            # Don't display "0% underdog" — either skip or say "drawing dead"
            elif eq_pct == 0 and eq == 0:
                parts.append("drawing dead at showdown")
            # else: equity is None/0 fallback — skip silently
        elif last_net < -5 and last_stack and last_stack <= 12:
            parts.append(f"busted short ({last_stack:.0f}BB)")

        # 2. All-in run across the tournament
        t_ids = {h.get('id') for h in t_hands}
        t_eais = [e for e in (eai_hands or []) if e.get('id') in t_ids]
        if t_eais:
            n_ai = len(t_eais)
            n_fav = sum(1 for e in t_eais if e.get('is_favorite'))
            n_won = sum(1 for e in t_eais
                        if e.get('id') and
                        any(h.get('id') == e['id'] and h.get('won')
                            for h in t_hands))
            if n_ai >= 2:
                parts.append(f"{n_won}/{n_ai} all-ins won")

        # 3. Card quality in last 25% of hands (or last 15, whichever is more)
        tail_n = max(15, n // 4)
        tail = t_hands[-tail_n:]
        from gem_analyzer import normalize_hand
        tail_premiums = sum(1 for h in tail
                           if normalize_hand(h.get('cards', [])) in PREMIUMS)
        tail_strong = sum(1 for h in tail
                          if normalize_hand(h.get('cards', [])) in STRONG)
        tail_vpip = sum(1 for h in tail if h.get('vpip'))
        if tail_premiums == 0 and tail_strong <= 1 and len(tail) >= 15:
            parts.append(f"card dead last {len(tail)} hands")
        elif tail_premiums >= 3:
            parts.append(f"{tail_premiums} premiums last {len(tail)}")

        # 4. Biggest single pot lost (if significant)
        worst = min(t_hands, key=lambda h: h.get('net_bb', 0))
        worst_net = worst.get('net_bb', 0)
        if worst_net < -15 and worst != last:
            _wc = _combo_to_chart(worst.get('cards', []))
            parts.append(f"lost {worst_net:.0f}BB pot" +
                         (f" ({_wc})" if _wc and _wc != '?' else ''))

        # 5. Positive tournament — highlight what went right
        if net > 0 and not parts:
            best = max(t_hands, key=lambda h: h.get('net_bb', 0))
            best_net = best.get('net_bb', 0)
            best_eai = eai_by_id.get(best.get('id', ''))
            if best_eai and best_eai.get('hero_equity') is not None:
                _beq = best_eai['hero_equity']
                _beq_pct = _beq * 100.0 if _beq <= 1.5 else _beq
                parts.append(f"won key {_beq_pct:.0f}% all-in (+{best_net:.0f}BB)")
            elif best_net > 15:
                parts.append(f"won +{best_net:.0f}BB pot")

        narratives[tname] = '; '.join(parts) if parts else ''
    return narratives


# ============================================================
# SECTION XIV — APPENDIX: FULL HAND DETAILS
# ============================================================

def _oversize_open_note(h):
    """v8.12.8 QA-GPT P1.5 (Ron, 66632137: "no comment on the 4BB open?"):
    a villain's outsized open is a teaching moment. Info-only — never a
    verdict input; skips jams and short stacks (open-jamming is normal)."""
    try:
        eff = h.get('eff_stack_bb') or h.get('stack_bb') or 0
        if eff < 20:
            return ''
        for a in (h.get('action_ledger') or []):
            if a.get('street') != 'preflop':
                continue
            act = a.get('action')
            if act in ('raises', 'bets'):
                if a.get('player') == h.get('hero') or a.get('is_all_in'):
                    return ''
                _open_to = 1.0 + (a.get('amount_bb') or 0)  # increment + BB
                if _open_to >= 3.5:
                    pos = a.get('position', '?')
                    return (f"📏 **Sizing read:** {pos}'s {_open_to:.1f}BB "
                            "open is oversized — population-wise often "
                            "recreational/polarized. Tighten flats OOP and "
                            "prefer value-heavy 3-bets against it.")
                return ''
        return ''
    except Exception:
        return ''


def _emit_villain_street_notes(doc, s, hid, hid_short):
    """Street-grouped villain evidence notes under the hand grid.
    Shared by XIV.A and the XIV.B stubs — v8.12.8 QA2: an evidence
    badge on a stub hand had no paired note block (it only existed on
    the XIV.A path). Returns True when the block was emitted."""
    # v8.8.6 VH Phase 4: yellow street notes for villain coaching
    _vi_data_xiv = s.get('villain_intel') or {}
    # v8.8.6 fix: atoms_by_hand keyed by full hid (TM60...); try full then short
    _abh_xiv = _vi_data_xiv.get('atoms_by_hand', {}) or {}
    _h_atoms = _abh_xiv.get(hid, []) or _abh_xiv.get(hid_short, [])
    if _h_atoms:
        _streets_with_notes = {}
        for _a in _h_atoms:
            _st = _a.get('street', '')
            if _st:
                _streets_with_notes.setdefault(_st, []).append(_a)
        if _streets_with_notes:
            doc.w("<div class='villain-street-notes'>")
            for _st in ('preflop', 'flop', 'turn', 'river'):
                if _st not in _streets_with_notes:
                    continue
                for _a in _streets_with_notes[_st]:
                    _sig = _a.get('signal', '')
                    _sug = _a.get('suggests', '')
                    _sw = _a.get('so_what', '')
                    _ev = _a.get('evidence_text', '')
                    _dt = _a.get('default_timing', '')
                    _alias = _a.get('villain_alias', '')
                    if not (_sug or _sw or _ev):
                        continue
                    # Badge: Pivot for aggro shift; v8.12.8 QA-GPT P1.4:
                    # cross-hand pattern reads (blind overfolds) are FUTURE
                    # exploit inventory, not a tell about THIS decision —
                    # label them so the reader doesn't hunt for an in-hand
                    # action that explains them (66701547).
                    if _sig == 'passive_aggro_pivot':
                        _badge = '⚠ Pivot'
                    elif _sig == 'repeated_blind_overfold':
                        _badge = '🧭 Future read'
                    else:
                        _badge = '❗ Note'
                    # Signal label: human-readable signal name (not atom label which duplicates badge emoji)
                    _sig_label = _sig.replace('_', ' ').title()
                    _vpos = _a.get('villain_position', '')
                    _vk = _a.get('villain_key', '')
                    _vnum = ''
                    if _vk:
                        _va_aliases = _vi_data_xiv.get('villain_aliases', {})
                        _va_entry = _va_aliases.get(_vk, {})
                        _vnum = _va_entry.get('v_number', '')
                    # Header: STREET badge — Signal Label
                    _line = (f"<span class='vsn-street'>{_st.upper()}</span> "
                             f"<strong>{_badge}</strong> — {_sig_label}")
                    doc.w(f"<p class='vsn-entry vsn-header'>{_line}</p>")
                    # Villain line: alias · V-code · position. v8.12.8
                    # (QA F, 65698846 "V10 · V10"): dedupe is
                    # case/whitespace-insensitive, and an alias that
                    # already embeds the V-code drops the bare code.
                    _v_parts, _v_seen = [], set()
                    for _vp_p in (_alias, _vnum, _vpos):
                        _vp_k = (_vp_p or '').strip().lower()
                        if not _vp_k or _vp_k in _v_seen:
                            continue
                        if (_vp_p == _vnum and _alias
                                and _vp_k in _alias.lower()):
                            continue
                        _v_seen.add(_vp_k)
                        _v_parts.append(_vp_p)
                    if _v_parts:
                        doc.w(f"<p class='vsn-entry vsn-villain'>Villain: {' · '.join(_v_parts)}</p>")
                    # Action (trigger_action or villain_action)
                    _trig = _a.get('trigger_action', '') or _a.get('villain_action', '')
                    if _trig:
                        doc.w(f"<p class='vsn-entry'>Action: {_trig}</p>")
                    # v8.12.8 QA3 (66701547 "WHAT IS THE TELL!?"): the
                    # evidence text carries what the villain actually DID
                    # (incl. cross-hand counts) — it was collected but
                    # never rendered here.
                    if _ev and _ev != _trig:
                        doc.w(f"<p class='vsn-entry vsn-evidence'>"
                              f"Evidence: {_ev}</p>")
                    if _sug:
                        doc.w(f"<p class='vsn-entry vsn-suggests'>What it suggests: {_sug}</p>")
                    if _sw:
                        doc.w(f"<p class='vsn-entry vsn-sowhat'><em>So what?</em> {_sw}</p>")
                    if _dt:
                        doc.w(f"<p class='vsn-entry vsn-timing'>Actionable now? {_dt}</p>")
                    # Read impact: dimension + strength
                    _dim = _a.get('dimension', '')
                    _str = _a.get('strength', 0)
                    if _dim and _str:
                        _dim_label = _dim.replace('_', ' ').title()
                        doc.w(f"<p class='vsn-entry vsn-impact'>Read impact: {_dim_label} +{_str}</p>")
            doc.w("</div>")
            doc.w("")
            return True
    return False


def _solver_confirm_note(hid, rd):
    """B225/B235 (Ron review 2026-05-25): if the IV.6 Solver Confirmation Pass
    evaluated this hand, return the solver's verdict + EV detail so the
    appendix hand description carries it in the yellow analyst-notes block.

    B235: two fixes — (1) the note now fires for ALL solver verdicts, not just
    CONFIRMED. A DENIED hand (solver says checking ≥ betting) is a 👍 — Ron
    wants 'checking is correct, confirmed by solver' shown, not silence. A
    NEUTRAL hand (sub-0.2BB) is reported as too-close-to-call. (2) candidates
    are read from aggression_solver_pass['candidates'] (the B230 union of
    heuristic flags + the 30-hand screen), not the heuristic-only
    missed_aggression list — screened hands were returning None.
    Returns a markdown string or None."""
    sp = (rd or {}).get('aggression_solver_pass', {}) or {}
    cands = sp.get('candidates') or []
    if not cands:
        cands = (rd.get('aggression_analysis', {}) or {}).get('missed_aggression', [])
    c = next((x for x in cands if x.get('hand_id') == hid), None)
    if not c:
        return None
    evb = c.get('solver_ev_bet')
    evc = c.get('solver_ev_check')
    evd = c.get('solver_ev_delta')
    pct = c.get('solver_test_bet_pct', 60)
    if evd is None:
        return None
    # v8.12.8 QA: this note is injected into raw-HTML <p> contexts (the
    # agg-notes block + the XIV.B auto note), so markdown stayed literal
    # on screen ("*Solver check:* **Confirmed...**") — emit HTML directly.
    _link = ("<a href='#sec-5-6' class='xref'>See S5.6 Solver "
             "Confirmation Pass ↑</a>")
    if hid in (sp.get('confirmed', []) or []):
        return (f"<em>Solver check:</em> 🎯 <strong>Confirmed missed "
                f"value</strong> — a {pct}%-pot river bet is "
                f"<strong>{evd:+.2f} BB</strong> over checking "
                f"(EV bet {evb:+.2f} vs check {evc:+.2f} BB), tested on a "
                f"synthetic bet because Hero checked. {_link}")
    if hid in (sp.get('denied', []) or []):
        return (f"<em>Solver check:</em> 👍 <strong>Check confirmed "
                f"correct</strong> — the solver agrees: a {pct}%-pot river "
                f"bet is <strong>{evd:+.2f} BB</strong> vs checking "
                f"(EV bet {evb:+.2f} vs check {evc:+.2f} BB), so "
                f"checking is the better line here. {_link}")
    # NEUTRAL / below the 0.2 BB noise floor
    return (f"<em>Solver check:</em> ⚪ <strong>Too close to call</strong> — "
            f"bet vs check is only {evd:+.2f} BB ({pct}%-pot test: EV bet "
            f"{evb:+.2f} vs check {evc:+.2f} BB), inside the 0.2 BB noise "
            f"floor — neither line is clearly better. {_link}")


def _why_here_text(anchor, label):
    """B165 (Ron 2026-05-24): a plain-language reason a hand sits in XIV.B,
    keyed off its citing section — no hand is left in the appendix without
    an explanation of why it's there.
    Returns (text, street_hint) where street_hint is a validated street name
    when deterministic from the anchor, or '' when the street depends on
    hand-level data the caller must supply."""
    a = (anchor or '').lower()
    if 'xiii-1' in a:
        return ("Flagged as a Wide Open — Hero opened wider than the "
                "position's target tier (chart comparison in XIII.1).",
                'preflop')
    if 'xiii-3' in a:
        return ("Flagged as a Missed Open — a first-in spot the chart opens "
                "but Hero folded (XIII.3).",
                'preflop')
    if 'xiii-4' in a:
        return ("Flagged in the session mistake review — see XIII.4 for the "
                "leak detail.", '')
    if 'xiii-5' in a or 'top-leaks' in a or 'mda' in a:
        return ("A population-exploit spot flagged by the MDA overlay (XIII.5).",
                '')
    if 'xiii-6' in a:
        return ("A large-loss hand audited in XIII.6.", '')
    if 'viii-3' in a:
        return ("Selected for the GTO Wizard study shortlist — drill this "
                "spot in the solver (VIII.3).", '')
    if 'viii-4' in a:
        return ("A check-raise Hero made this session — review spot "
                "selection and sizing (VIII.4).", '')
    if 'i-3' in a:
        return ("A large-loss hand (>25BB lost) — full audit in I.3.", '')
    if 'viii-5' in a or 'blind' in a.lower() or 'defend' in a.lower():
        return ("A missed defense from the blinds — Hero folded a hand that "
                "should have been defended per the position defend range.",
                'preflop')
    return (f"Referenced: {label}", '')


def _allin_range_note(h):
    """Q5 (DISABLED v8.14.1, GPT rev): legacy "Range check:" block.

    This path used a hardcoded PUSH_10BB chart + ceil depth buckets and produced
    membership verdicts that CONTRADICTED the canonical "Range evidence" block
    (gem_ranges.build_range_evidence, rendered in every hand-detail card) — e.g.
    72806650 showed old "Range check: A2s outside SB open-shove 10BB" right above
    the evidence "A2s: INSIDE SB open-shove 12BB". The canonical selector is now
    the single source of truth, so this returns '' (removed) rather than risk a
    second, divergent membership claim."""
    return ''
    if not h.get('pf_allin'):  # pragma: no cover  (legacy body kept for history)
        return ''
    try:
        from gem_ranges import (normalize_hand_class as _nrm,
                                load_ranges as _lr, range_boundary as _rb)
    except Exception:
        return ''
    cards = h.get('cards', [])
    if len(cards) < 2:
        return ''
    hc = _nrm(cards)
    pos = h.get('position', '?')
    stk = h.get('eff_stack_bb_at_decision') or h.get('stack_bb', 99)
    ranges = _lr()
    # v8.14.1 hotfix (#71725727): the Range-check shows the human chart label,
    # never the raw internal id (PUSH_10BB_CO / REJAM_SBvsCO mean nothing to Ron).
    from gem_chart_labels import chart_display_label as _cdl
    parts = []

    hero_jammed = False
    if h.get('first_in'):
        for a in (h.get('action_ledger') or []):
            if (a.get('player') == h.get('hero')
                    and a.get('street') == 'preflop'
                    and a.get('action') in ('raises', 'bets')
                    and a.get('is_all_in')):
                hero_jammed = True
                break

    if hero_jammed and stk <= 25:
        key = f'PUSH_10BB_{pos}'
        rng = ranges.get(key, {})
        if rng:
            inside = hc in rng
            icon = '✅' if inside else '❌'
            boundary = _rb(', '.join(rng.keys())) if hasattr(_rb, '__call__') else ''
            bnd = f' (boundary: {boundary})' if boundary else ''
            parts.append(f'{icon} **{hc}** {"in" if inside else "outside"} '
                         f'the {_cdl(key)} range ({len(rng)} hand classes){bnd}')

    if not hero_jammed and stk <= 30:
        jammer = h.get('jammer_position', '')
        if jammer:
            depth = ('12BB' if stk <= 14 else '15BB' if stk <= 17
                     else '20BB' if stk <= 25 else '30BB')
            key = f'CALLJAM_{depth}_vs{jammer}'
            rng = ranges.get(key, {})
            if rng:
                inside = hc in rng
                icon = '✅' if inside else '❌'
                boundary = _rb(', '.join(rng.keys())) if hasattr(_rb, '__call__') else ''
                bnd = f' (boundary: {boundary})' if boundary else ''
                # v8.14.1 rev-3 (Blocker 4): humanize the call-jam chart id like
                # the open/re-jam siblings above (rev-1 missed this one line, so
                # raw CALLJAM_* still leaked into the Range-check copy).
                parts.append(f'{icon} **{hc}** {"in" if inside else "outside"} '
                             f'the {_cdl(key)} range ({len(rng)} hand classes){bnd}')

    opener = h.get('opener_position', '')
    if opener and pos and stk <= 30:
        rj_key = f'REJAM_{pos}vs{opener}'
        rj_rng = ranges.get(rj_key, {})
        if rj_rng:
            inside = hc in rj_rng
            icon = '✅' if inside else '❌'
            parts.append(f'{icon} **{hc}** {"in" if inside else "outside"} '
                         f'the {_cdl(rj_key)} range ({len(rj_rng)} hand classes)')

    if not parts:
        return ''
    return '\n\n**Range check:**\n' + '\n'.join(f'- {p}' for p in parts)


def _classify_timing(exp_or_atom, hero_decision_street=None,
                     hero_decision_index=None):
    """Classify when evidence was available relative to Hero's decision.

    Returns one of:
      'known_before'        — read established from prior hands
      'same_hand_before'    — same-hand evidence available before Hero acted
      'same_hand_after'     — evidence created after Hero's decision point
      'unknown'             — cannot determine

    v8.8.6: Trust requirement — a missed exploit can only be shown as a miss
    if timing confirms the read was available before Hero acted.
    """
    avail = exp_or_atom.get('available_before_action_index')
    read_src = exp_or_atom.get('read_source', '')
    same_hand = exp_or_atom.get('same_hand_actionable', False)

    # Prior-hand evidence is always 'known_before'
    if read_src == 'prior_atoms_mapped':
        return 'known_before'
    if read_src == 'profiler_archetype':
        return 'known_before'

    # Same-hand evidence needs index comparison
    if same_hand and avail is not None:
        if hero_decision_index is not None and avail <= hero_decision_index:
            return 'same_hand_before'
        elif hero_decision_index is not None:
            return 'same_hand_after'
        # No hero decision index but atom says same_hand_actionable
        return 'same_hand_before'

    if read_src == 'same_hand_pivot':
        return 'same_hand_before'

    return 'unknown'


_TIMING_LABELS = {
    'known_before': 'Known before Hero acted',
    'same_hand_before': 'Detected earlier in this hand, before Hero decided',
    'same_hand_after': 'Detected after Hero decided (not actionable)',
    'unknown': 'Timing unclear — evidence note only',
}


def _build_hand_opponent_contexts(hands, s, rd, *, analyst_review=None):
    """Build per-hand 4-bucket opponent context for modal coaching blocks.

    Returns dict mapping hand_id → list of context dicts, each with:
      bucket: 'exploit_miss' | 'good_exploit' | 'villain_evidence' | 'passive_read'
      + timing, coaching, villain info fields

    If analyst_review is provided (from load_analyst_villain_review), overlay
    analyst verdicts per architecture §5.2:
      - 'rejected' → filter from rendering (Option A), count for debug
      - 'confirmed' → add analyst_coaching + badge
      - 'borderline' → add softer framing + analyst_coaching
      - 'upgraded' → show as learning opportunity with analyst coaching

    v8.8.6 Villain Hand Details Phase 2 + v8.9.0-prep analyst overlay.
    """
    vi = s.get('villain_intel') or {}
    # v8.8.6 fix: atoms_by_hand is already indexed by hand_id
    # (was: vi.get('all_atoms') which doesn't exist → Bucket C always empty)
    atoms_by_hid = vi.get('atoms_by_hand', {}) or {}
    all_exploits = vi.get('exploit_opportunities', []) or []
    aliases = vi.get('villain_aliases', {}) or {}
    read_states = vi.get('read_states', {}) or {}

    # v8.13.0: villain exploitation teaching-layer inputs. The teaching object
    # is a render-facing PROJECTION of the already-stamped exploit/atom/read
    # data (gem_villain_teaching invents nothing). Attached per context below.
    try:
        from gem_villain_teaching import (teaching_from_exploit as _vt_exp,
                                          teaching_from_atom as _vt_atom)
        from gem_villain_intel import SIGNAL_COACHING as _vt_sig
        _vt_ok = True
    except Exception:
        _vt_ok = False
    _vt_atoms_by_villain = vi.get('atoms_by_villain', {}) or {}
    _vt_pko_by_hand = (rd.get('pko_research') or {}).get('by_hand', {}) or {}
    # GG sessions are online MTT/PKO; live reads are never cross-applied here.
    _vt_population = (s.get('session_population')
                     or rd.get('session_population') or 'online')

    # v8.9.0-prep: analyst review overlay lookup
    # by_hv: (hand_id_short, villain_key) → list of analyst review dicts
    _ar_by_hv = {}
    _ar_rejected_count = 0
    if analyst_review:
        _ar_by_hv = analyst_review.get('by_hand_villain', {})

    def _find_analyst(hid_short, vk, source_type):
        """Look up analyst review for a specific context."""
        reviews = _ar_by_hv.get((hid_short, vk), [])
        for r in reviews:
            if r.get('source_type') == source_type:
                return r
        # Fallback: any review for this hand+villain pair
        return reviews[0] if reviews else None

    # Index exploits by hand_id
    exploits_by_hid = {}
    for exp in all_exploits:
        hid = exp.get('hand_id', '')
        if hid:
            exploits_by_hid.setdefault(hid, []).append(exp)

    # Collect all villain keys that appear in any hand
    all_villain_keys = set()
    for _atom_list in atoms_by_hid.values():
        for atom in _atom_list:
            vk = atom.get('villain_key', '')
            if vk:
                all_villain_keys.add(vk)
    for exp in all_exploits:
        vk = exp.get('villain_key', '')
        if vk:
            all_villain_keys.add(vk)

    # Build per-hand contexts for every hand in appendix
    app_hids = set(rd.get('appendix_hand_ids_all', []))
    result = {}

    for hid in app_hids:
        contexts = []
        h_atoms = atoms_by_hid.get(hid, [])
        h_exploits = exploits_by_hid.get(hid, [])
        _exploit_vks = set()

        # --- Buckets A & B: exploit opportunities ---
        for exp in h_exploits:
            vk = exp.get('villain_key', '')
            _exploit_vks.add(vk)
            hero_street = exp.get('hero_decision_street', '')
            hero_idx = exp.get('hero_decision_index')
            timing = _classify_timing(exp, hero_street, hero_idx)
            timing_label = _TIMING_LABELS.get(timing, timing)
            outcome = exp.get('exploit_outcome', '')
            severity = exp.get('severity', 'C')

            if outcome == 'missed':
                # Trust gate: only show as miss if timing confirms availability
                if timing in ('known_before', 'same_hand_before'):
                    bucket = 'exploit_miss'
                else:
                    # Downgrade to evidence note
                    bucket = 'villain_evidence'
            elif outcome == 'good':
                bucket = 'good_exploit'
            else:
                bucket = 'villain_evidence'

            va = aliases.get(vk, {})
            rs = read_states.get(vk, {})

            # v8.9.0-prep: analyst overlay for exploit contexts
            _hid_short = hid[-8:] if len(hid) > 8 else hid
            _src = ('exploit_miss' if outcome == 'missed' else
                    'exploit_good' if outcome == 'good' else
                    'timing_unclear')
            _ar = _find_analyst(_hid_short, vk, _src)

            # Requirement D (Option A): filter rejected in Python
            if _ar and _ar.get('analyst_verdict') == 'rejected':
                _ar_rejected_count += 1
                continue

            _ctx = {
                'bucket': bucket,
                'villain_alias': va.get('alias', exp.get('villain_alias', '')),
                'v_number': va.get('v_number', ''),
                'read_label': exp.get('exploit_read_label', ''),
                'timing': timing,
                'timing_label': timing_label,
                'hero_action': exp.get('hero_action', ''),
                'recommended': exp.get('recommended_exploit', ''),
                'suggests': exp.get('suggests', ''),
                'so_what': exp.get('so_what', ''),
                'severity': severity,
                'exploit_detector': exp.get('exploit_detector', ''),
                'evidence_text': exp.get('evidence_text', ''),
                'assumption_source': exp.get('assumption_source', ''),
            }
            # Overlay analyst fields when reviewed
            if _ar:
                _ctx['analyst_reviewed'] = True
                _ctx['analyst_verdict'] = _ar.get('analyst_verdict', '')
                _ctx['analyst_coaching'] = _ar.get('analyst_coaching', '')
                _ctx['analyst_severity'] = _ar.get('analyst_severity', '')
                _ctx['analyst_note'] = _ar.get('analyst_note', '')
            if _vt_ok:
                _ctx['teaching'] = _vt_exp(exp, read_states, _vt_atoms_by_villain,
                                           population=_vt_population,
                                           pko_by_hand=_vt_pko_by_hand)
            contexts.append(_ctx)

        # --- Bucket C: atoms with no exploit in this hand ---
        # v8.12.8 (exploitation QA P1, TM6066701378): dedupe was hand+villain
        # only — Torch's good_exploit (preflop steal) suppressed his
        # UNRELATED multiway_donk atom on the flop, losing the exact
        # conflict worth teaching. Now an atom is suppressed only when it
        # is the event that FED the exploit: same villain, same street,
        # and an overfold-family signal (steal exploits are built from
        # prior blind-overfold reads).
        _exploit_cover = {(e.get('villain_key', ''),
                           e.get('hero_decision_street', '') or 'preflop')
                          for e in h_exploits}
        _atom_vks = set()
        for atom in h_atoms:
            vk = atom.get('villain_key', '')
            _atom_vks.add(vk)
            if ((vk, atom.get('street', '')) in _exploit_cover
                    and atom.get('signal', '') == 'repeated_blind_overfold'):
                continue  # this atom IS the exploit's evidence — no dup card
            timing = _classify_timing(atom)
            timing_label = _TIMING_LABELS.get(timing, timing)
            va = aliases.get(vk, {})

            # v8.9.0-prep: analyst overlay for atom contexts
            # Atoms may be reviewed as mixed_signal or learning_hand
            _hid_short = hid[-8:] if len(hid) > 8 else hid
            _ar = (_find_analyst(_hid_short, vk, 'mixed_signal') or
                   _find_analyst(_hid_short, vk, 'learning_hand'))

            if _ar and _ar.get('analyst_verdict') == 'rejected':
                _ar_rejected_count += 1
                continue

            _ctx = {
                'bucket': 'villain_evidence',
                'villain_alias': va.get('alias', atom.get('villain_alias', '')),
                'v_number': va.get('v_number', ''),
                'signal': atom.get('signal', ''),
                'signal_label': atom.get('label', ''),
                'suggests': atom.get('suggests', ''),
                'so_what': atom.get('so_what', ''),
                'timing': timing,
                'timing_label': timing_label,
                'street': atom.get('street', ''),
                'evidence_text': atom.get('evidence_text', ''),
                # v8.9.7 B141: carry actionability so the renderer only pins
                # same-hand-actionable notes to in-hand street cards; cross-hand
                # aggregates (repeated_blind_overfold etc.) go to General reads.
                'same_hand_actionable': bool(atom.get('same_hand_actionable', False)),
            }
            if _ar:
                _v = _ar.get('analyst_verdict', '')
                # 'upgraded' → promote atom from evidence to learning opportunity
                if _v == 'upgraded':
                    _ctx['bucket'] = 'analyst_learning'
                _ctx['analyst_reviewed'] = True
                _ctx['analyst_verdict'] = _v
                _ctx['analyst_coaching'] = _ar.get('analyst_coaching', '')
                _ctx['analyst_severity'] = _ar.get('analyst_severity', '')
                _ctx['analyst_note'] = _ar.get('analyst_note', '')
            if _vt_ok:
                _ctx['teaching'] = _vt_atom(atom, read_states, _vt_atoms_by_villain,
                                            signal_coaching=_vt_sig,
                                            population=_vt_population,
                                            pko_by_hand=_vt_pko_by_hand)
            contexts.append(_ctx)

        # --- Bucket D: villain with known read but no atom/exploit ---
        # Find villain keys involved in this hand via action_ledger
        hand_data = s.get('_hands_by_id', {}).get(hid)
        if hand_data:
            _al = hand_data.get('action_ledger') or []
            _tid = hand_data.get('tournament_id', '')
            _hand_players = set()
            for a in _al:
                p = a.get('player', '')
                if p:
                    _hand_players.add(f"{_tid}|{p}")
            for vk in _hand_players:
                if vk in _exploit_vks or vk in _atom_vks:
                    continue  # already have a context for this villain
                rs = read_states.get(vk, {})
                va = aliases.get(vk, {})
                if not rs.get('primary_read') and not va.get('alias'):
                    continue  # no known read
                _pr = rs.get('primary_read', '')
                _n_ev = va.get('n_evidence', 0)
                if not _pr and _n_ev == 0:
                    continue
                contexts.append({
                    'bucket': 'passive_read',
                    'villain_alias': va.get('alias', ''),
                    'v_number': va.get('v_number', ''),
                    'read_label': _pr.split(' ', 1)[1] if _pr and ' ' in _pr else _pr,
                    'n_evidence': _n_ev,
                    'confidence': rs.get('confidence', ''),
                })

        if contexts:
            # Normalize key to 8-digit short form (matches modal hid parameter)
            _short = hid[-8:] if len(hid) > 8 else hid
            result[_short] = contexts

    return result


def _build_villain_badges(hid, s):
    """Build villain badge dict for the hand grid: (street, action_index) → badges.

    Each badge is {type: 'note'|'pivot'|'miss'|'good', label: str}.
    v8.8.6 VH Phase 4.
    """
    vi = s.get('villain_intel') or {}
    # v8.8.6 fix: atoms_by_hand keyed by full hid; try full then short
    _abh = vi.get('atoms_by_hand', {}) or {}
    _hid_short = hid[-8:] if len(hid) > 8 else hid
    hand_atoms = _abh.get(hid, []) or _abh.get(_hid_short, [])
    all_exploits = vi.get('exploit_opportunities', []) or []
    badges = {}

    # v8.12.8 (QA F): villain-action evidence signals get a red ! badge ON
    # THE ACTION ROW so the grid mirrors the ❗ Note commentary (91 hands
    # had notes with no grid marker). Whitelist only signals whose
    # action_index points at the VILLAIN's own action; the renderer also
    # suppresses villain-type badges that land on a Hero row, so the
    # v8.8.9 BUG-4 mis-placement cannot recur.
    _SIG_BADGE = {
        'open_limp': 'Limp', 'limp_call': 'Limp-call',
        'multiway_donk': 'Donk', 'weird_minbet': 'Min-bet',
        'cold_call_3bet_oop': 'Cold-call',
        'weak_showdown_call': 'Station', 'calldown_weak_pair': 'Station',
    }
    # v8.12.8 QA2: the atom's action_index is a LEDGER position while the
    # grid keys rows by per-street index — the spaces drift (a Cold-call
    # badge landed on the villain's OPEN). Every badge therefore declares
    # the action kind it can sit on; the grid suppresses any badge whose
    # row doesn't match. Never-wrong beats sometimes-shown-wrong.
    _SIG_EXPECT = {
        'open_limp': ('calls',), 'limp_call': ('calls',),
        'multiway_donk': ('bets',), 'weird_minbet': ('bets',),
        'cold_call_3bet_oop': ('calls',),
        'weak_showdown_call': ('calls',), 'calldown_weak_pair': ('calls',),
    }
    for atom in hand_atoms:
        street = atom.get('street', '')
        idx = atom.get('action_index')
        if street and idx is not None:
            key = (street, idx)
            sig = atom.get('signal', '')
            _has_teaching = bool(atom.get('suggests') or atom.get('so_what')
                                 or atom.get('evidence_text'))
            if sig == 'passive_aggro_pivot':
                badges.setdefault(key, []).append(
                    {'type': 'pivot', 'label': 'Pivot',
                     'expect': ('bets', 'raises')})
            elif sig in _SIG_BADGE and _has_teaching:
                # red ! evidence badge — renders only if the ❗ Note block
                # below the grid carries the explanation (same atom)
                _alias = atom.get('villain_alias', '')
                badges.setdefault(key, []).append({
                    'type': 'evid', 'label': '! ' + _SIG_BADGE[sig],
                    'expect': _SIG_EXPECT.get(sig),
                    'tip': (f"{_alias + ': ' if _alias else ''}"
                            f"{_SIG_BADGE[sig]} tell — see the ❗ Note "
                            "below the grid for what it suggests")})

    for exp in all_exploits:
        if exp.get('hand_id') != hid:
            continue
        street = exp.get('hero_decision_street', '')
        idx = exp.get('hero_decision_index')
        # v8.9.7 B140: exploits frequently carry hero_decision_street but a
        # null hero_decision_index — use -1 sentinel so the table builder
        # pins the badge to Hero's last action on that street.
        if street and idx is None:
            idx = -1
        # support both field spellings used across the pipeline
        outcome = exp.get('exploit_outcome', '') or (
            'missed' if exp.get('auto_verdict') == 'missed_exploit' else
            'good' if exp.get('auto_verdict') == 'good_exploit' else '')
        if street and idx is not None:
            key = (street, idx)
            if outcome == 'missed':
                badges.setdefault(key, []).append({'type': 'miss', 'label': 'Miss'})
            elif outcome == 'good':
                badges.setdefault(key, []).append({'type': 'good', 'label': 'Good'})

    return badges if badges else None


def _emit_range_lens(doc, h, hid_short):
    """v8.16.3 Commentary & Range Explanation Upgrade v1 — append a compact,
    SOURCE-SAFE 'Range lens' line per street as its OWN ``<div class='analyst-notes'
    data-street='X'>`` block. The V25 modal harvests .analyst-notes by data-street
    and APPENDS clones in order, so this NEVER overwrites or drops existing
    commentary; it just adds a teaching line into the correct street card. Every
    line is skipped when its source is missing (no chart / no board / Hero did not
    act that street), so nothing is invented. All notation/buckets come from
    gem_ranges (chart hand-sets + phevaluator classifiers); no solver %, no
    per-combo villain claims."""
    try:
        import gem_ranges as _grl
        from gem_report_draft._helpers import (hand_range_evidence as _hre,
                                               get_ranges_cached as _grc)
    except Exception:
        return

    def _emit(street, text):
        if not text:
            return
        doc.w(f"<div class='analyst-notes' data-street='{street}'>")
        doc.w("")
        doc.w("\U0001F4D0 " + text)   # 📐 range-lens marker
        doc.w("")
        doc.w("</div>")
        doc.w("")

    # preflop: chart-backed; reuse the canonical evidence object so the lens can
    # never contradict the Range-evidence block's in/out wording.
    try:
        _ranges = _grc()
    except Exception:
        _ranges = None
    try:
        _ev = _hre(h, _ranges)
        if _ev:
            # v8.16.4 Obj 6: render path highlights the range expression in-place.
            _emit('preflop', _grl.preflop_range_lens(_ev, _ranges, highlight=True))
    except Exception:
        pass

    # v8.16.4 Objective 10: when Hero is all-in PREFLOP there is no later Hero
    # decision, so a postflop Range Lens would teach nothing about a choice Hero
    # never made — skip it (the preflop lens above still applies).
    if h.get('pf_allin'):
        return

    # postflop: per street Hero actually acted on, with a long-enough board.
    _board = h.get('board') or []
    _cards = h.get('cards') or []
    _hsa = h.get('hero_street_actions') or {}
    if len(_cards) == 2:
        for _street, _n in (('flop', 3), ('turn', 4), ('river', 5)):
            if len(_board) >= _n and _hsa.get(_street):
                try:
                    _emit(_street, _grl.postflop_range_lens(_cards, _board[:_n], _street))
                except Exception:
                    pass


def _emit_section_xiv_appendix(doc, s, rd, hands):
    """Appendix with readable full-hand details for hands the analyst flagged
    for review or judgment. Cross-linked from XIII.4.5 (Analyst-Reviewed
    Detector Flags) so Ron doesn't need to look them up in the poker app.

    v7.43 (Ron 2026-05-09): added per his request — analyst-reviewed hands
    in body, full HH detail down here.
    """
    doc.section("sec-18", "S18. Appendix — Hand Details",
                "full HH context for every hand_id cited in the report")

    # v8.7.0 PR2: inject villain intel data for JS popup
    _vi_data = (s.get('villain_intel') or {}).get('villain_aliases', {})
    if _vi_data:
        import json as _json_vi
        # Build a slim version with only popup-needed fields
        # Join read_states for archetype_label/emoji (alias record often empty)
        _vi_reads = (s.get('villain_intel') or {}).get('read_states', {}) or {}
        _vi_popup = {}
        for _vk, _va in _vi_data.items():
            _rs = _vi_reads.get(_vk, {})
            _pr = _rs.get('primary_read', '')
            # Split emoji from label: "📞 Sticky Passive" → emoji="📞", label="Sticky Passive"
            _pr_emoji = _pr.split(' ')[0] if _pr and ' ' in _pr else ''
            _pr_label = _pr.split(' ', 1)[1] if _pr and ' ' in _pr else _pr
            _pr_conf = _rs.get('confidence', '')
            # Canonical label: read_state (evidence-backed) > old profiler > empty
            # This prevents taxonomy drift where archetype=SOLID_REG but label=Aggressive
            _canon_label = _pr_label or _va.get('archetype_label', '') or ''
            _canon_emoji = _pr_emoji or _va.get('archetype_emoji', '') or ''
            _canon_code = _pr_label or _va.get('archetype', '') or ''
            _vi_popup[_vk] = {
                'alias': _va.get('alias', ''),
                'v_number': _va.get('v_number', ''),
                'archetype': _canon_code,
                'archetype_label': _canon_label,
                'archetype_emoji': _canon_emoji,
                'confidence': _pr_conf,
                'n_evidence': _va.get('n_evidence', 0),
                'evidence_atoms': _va.get('evidence_atoms_for_popup', []),
            }
        try:
            _vi_json = _json_vi.dumps(_vi_popup, ensure_ascii=False, default=str)
            # v8.12.0 R1: compressed payload via the single PB codec —
            # decoded lazily by PBData; no raw multi-100KB global emitted.
            from gem_report_draft._helpers import pb_payload_js as _pb_js_vi
            doc._extra_js.append(_pb_js_vi('villainIntel', _vi_json,
                                           len(_vi_popup)))
        except Exception:
            pass

        # v8.8.0: serialize exploit opportunities for JS drilldown
        _vi_exploits = (s.get('villain_intel') or {}).get('exploit_opportunities', []) or []
        if _vi_exploits:
            _exp_popup = []
            for _exp in _vi_exploits:
                _evk = _exp.get('villain_key', '')
                _eva = _vi_data.get(_evk, {})
                _ers = _vi_reads.get(_evk, {})
                # v8.8.3: use exploit_read_label (stamped at detection time)
                # instead of villain's overall primary_read
                _epr_raw = _exp.get('exploit_read_label', '')
                if not _epr_raw:
                    # Fallback for pre-v8.8.3 data
                    _epr_raw = _ers.get('primary_read', '')
                # v8.8.6: exploit_read_label is now canonical (no emoji).
                # Strip emoji prefix only from legacy labels (pre-v8.8.6 data).
                _epr_label = _epr_raw
                if _epr_raw and not _epr_raw[0].isalpha():
                    _epr_label = _epr_raw.split(' ', 1)[1] if ' ' in _epr_raw else _epr_raw
                _exp_popup.append({
                    'hand_id': _exp.get('hand_id', ''),
                    'villain_key': _evk,
                    'villain_alias': _eva.get('alias', ''),
                    'v_number': _eva.get('v_number', ''),
                    'read_label': _epr_label or 'Unknown',
                    'hero_decision_street': _exp.get('hero_decision_street', ''),
                    'hero_action': _exp.get('hero_action', ''),
                    'villain_read_before_decision': _exp.get('villain_read_before_decision', ''),
                    'auto_verdict': _exp.get('auto_verdict', ''),
                    'label': _exp.get('label', ''),
                    'badge': _exp.get('badge', ''),
                    'recommended_exploit': _exp.get('recommended_exploit', ''),
                    'evidence_text': _exp.get('evidence_text', ''),
                    'severity': _exp.get('severity', ''),
                    'exploit_detector': _exp.get('exploit_detector', ''),
                    'exploit_type': _exp.get('exploit_type', ''),
                    'exploit_outcome': _exp.get('exploit_outcome', ''),
                    'read_source': _exp.get('read_source', ''),
                    'exploit_read_label': _exp.get('exploit_read_label', ''),
                    'exploit_read_display': _exp.get('exploit_read_display', ''),
                    'assumption_source': _exp.get('assumption_source', ''),
                    'assumption_confidence': _exp.get('assumption_confidence', ''),
                    # v8.8.6 VH Phase 1: coaching fields
                    'suggests': _exp.get('suggests', ''),
                    'so_what': _exp.get('so_what', ''),
                    'default_timing': _exp.get('default_timing', ''),
                })
            try:
                _exp_json = _json_vi.dumps(_exp_popup, ensure_ascii=False, default=str)
                doc._extra_js.append(f'window.exploitOpportunities={_exp_json};')
            except Exception:
                pass

        # v8.8.5: serialize per-tournament P&L rows for sortable JS table
        _pnl_data = s.get('_per_tourney_pnl', []) or []
        if _pnl_data:
            import json as _json_pnl
            _pnl_rows = []
            # USD overlay for net/ROI
            _usd_pt = (rd.get('usd_overlay', {}) or {}).get('per_tournament') or []
            _usd_by_tid = {}
            for _u in _usd_pt:
                _utid = str(_u.get('tid', '') or '')
                if _utid:
                    _usd_by_tid[_utid] = _u
            for _t in _pnl_data:
                _utid = _t.get('tournament_id', '')
                _um = _usd_by_tid.get(_utid, {})
                _pnl_rows.append({
                    'date': _t.get('date', ''),
                    'name': _t.get('tournament', ''),
                    'bullets': _t.get('bullets', 1),
                    'hands': _t.get('hands', 0),
                    'buyin': _um.get('cost', _t.get('buyin', 0)),
                    'cash': _um.get('cash_total', 0),
                    'net_usd': _um.get('net', 0),
                    'roi': ((_um.get('net', 0) / _um['cost'] * 100)
                            if _um.get('cost') else 0),
                    'net_bb': round(_t.get('net_bb', 0), 1),
                    'bb100': round(_t.get('bb_per_100', 0), 1),
                    'format': _t.get('format', ''),
                })
            try:
                _pnl_json = _json_pnl.dumps(_pnl_rows, ensure_ascii=False, default=str)
                doc._extra_js.append(f'window.perTournamentPnlRows={_pnl_json};')
                doc._extra_js.append('if(window.initPerTournamentPnlTable)window.initPerTournamentPnlTable();')
            except Exception:
                pass

    # v8.8.6 VH Phase 2 + v8.9.0-prep analyst overlay:
    # build and serialize hand opponent contexts
    _analyst_villain_review = rd.get('analyst_villain_review')
    try:
        _hoc = _build_hand_opponent_contexts(
            hands, s, rd, analyst_review=_analyst_villain_review)
        if _hoc:
            import json as _json_hoc
            # v8.12.0 R1: compressed payload (was ~1.2MB raw -> ~80KB).
            from gem_report_draft._helpers import pb_payload_js as _pb_js_hoc
            doc._extra_js.append(_pb_js_hoc(
                'handOpponentContexts',
                _json_hoc.dumps(_hoc, ensure_ascii=False, default=str),
                len(_hoc)))
    except Exception:
        pass

    # Collect hands to surface: any hand with an analyst verdict OR in the
    # human-review needs list, OR an analyst commentary (busts, coolers, etc).
    analyst_pre = (rd.get('analyst_commentary') or {})
    # v8.7.3 FIX (handover Bug 4): filter non-dict scalar metadata keys
    # (session_date, date_compact etc.) that crash .get() on string values
    analyst_pre = {k: v for k, v in analyst_pre.items()
                   if isinstance(v, dict) or k == '__synthesis__'}
    synth = analyst_pre.get('__synthesis__', {}) or {}
    _mr_raw_xiv = synth.get('mistakes_review', {}) if isinstance(synth, dict) else {}
    mistakes_review = _mr_raw_xiv if isinstance(_mr_raw_xiv, dict) else {}

    # Priority 1: analyst-reviewed mistakes (the ones from XIII.4.5)
    rev = rd.get('reviewed_mistakes', {})
    needs_review_list = rev.get('needs_review', []) or []
    review_hand_ids = set()
    for m in needs_review_list:
        review_hand_ids.add(m.get('id'))

    # Priority 2: any other hand with per-hand analyst commentary (busts, etc)
    analyst_judged_ids = {hid for hid, cmt in analyst_pre.items()
                          if isinstance(cmt, dict) and hid.startswith('TM')}

    # Full-entry list (XIV.A): analyst-reviewed + analyst-judged
    hand_ids_full = list(review_hand_ids)
    for hid in analyst_judged_ids:
        if hid not in review_hand_ids:
            hand_ids_full.append(hid)

    # Stub list (XIV.B): all referenced hands NOT already in full list
    # — gives Ron click-through for every body citation per Ron 2026-05-11
    all_app_ids = set(rd.get('appendix_hand_ids_all', []) or [])
    hand_ids_stub = sorted(all_app_ids - set(hand_ids_full))

    hands_by_id = {h.get('id', ''): h for h in hands}

    # ============ XIV.A — Full Reviewed Entries ============
    if hand_ids_full:
        doc.w("")
        doc.w("<details open>")
        doc.w(f"<summary><strong>XIV.A Reviewed Hands "
              f"({len(hand_ids_full)})</strong> — click to collapse</summary>")
        doc.w("")
        doc.w("*Hands with analyst notes — large-loss audits, coolers, reviewed mistakes, "
              "promoted classifications.*")
        doc.w("")
    elif not hand_ids_stub:
        doc.w("👍 No hands flagged for appendix this session.")
        doc.w("")
        return

    hand_ids_to_show = hand_ids_full

    for hid in hand_ids_to_show:
        h = hands_by_id.get(hid)
        if not h:
            continue
        cmt = analyst_pre.get(hid, {}) or {}
        # v8.7.3 FIX (handover Bug 4): guard non-dict analyst entries
        if not isinstance(cmt, dict):
            cmt = {}
        review_cmt = mistakes_review.get(hid, {}) or {}
        # v8.7.3 FIX (handover Bug 3): type-guard — review_cmt can be string
        if isinstance(review_cmt, str):
            review_cmt = {'verdict': '', 'argument': review_cmt}
        if not isinstance(review_cmt, dict):
            review_cmt = {}
        hid_short = hid[-8:] if len(hid) > 8 else hid
        verdict = cmt.get('verdict', '') or review_cmt.get('verdict', '')
        # v8.8.9 BUG-3: fallback to HIGH-confidence auto-verdict from pipeline
        _auto_v = rd.get('auto_verdicts', {}).get(hid, {})
        _is_auto_verdict = False
        if not verdict and _auto_v.get('verdict'):
            verdict = _auto_v['verdict']
            _is_auto_verdict = True

        # B58 (v7.55) + B67 (v7.56) + B74 (v7.56, Ron 2026-05-18):
        # Heading shows chip outcome via colored BB span (green/red bg) — the
        # ➕/➖ emojis are both purple in many fonts which defeated the purpose.
        # Verdict signal stays on the *Verdict:* line below.
        cards = ''.join(h.get('cards', []))
        pos = h.get('position', '?')
        stack_bb = h.get('stack_bb') or 0
        net_bb = h.get('net_bb') or 0
        # Heading BB has its own span class for green/red bg styling
        if net_bb > 0:
            bb_html = f"<span class='hand-net-pos'>+{net_bb:.1f} BB</span>"
        elif net_bb < 0:
            bb_html = f"<span class='hand-net-neg'>{net_bb:.1f} BB</span>"
        else:
            bb_html = f"<span class='hand-net-neu'>0 BB</span>"
        # Phase 4.5: hand-detail-card wrapper (v27 spec §4)
        app_details = rd.get('appendix_hand_details', {}).get(hid, {})
        _vaa_fmt = _html_escape(h.get('format', '') or '')
        _vaa_ph = _html_escape(h.get('tournament_phase', '') or '')
        # B-V10 precedence: eff_stack_bb_at_decision is the decision-effective
        # depth (jams/CVJ); eff_stack_bb is the flop-context fallback.
        _vaa_eff = (h.get('eff_stack_bb_at_decision') or h.get('eff_stack_bb')
                    or h.get('stack_bb') or 0)
        _vaa_t = _html_escape(str(h.get('tournament', '') or ''))
        _state._FULL_CARD_IDS.add(hid_short)  # v8.16.2 Phase B: full card -> never also a XIV.C stub
        doc.w(f"<article class='hand-detail-card' data-hand-id='{hid_short}' "
              f"data-format='{_vaa_fmt}' data-phase='{_vaa_ph}' "
              f"data-eff-bb='{_vaa_eff:.1f}' data-tournament='{_vaa_t}'>")
        # Phase 4.7 C3: mh-top / mh-title wrapper (v29 vocabulary)
        doc.w("<div class='mh-top'><div class='mh-title'>")
        doc.w(f"<<ANCHOR:sec-app-hand-{hid_short}>>")
        _agl = _agg_gate_label(h.get('id') or hid_short, rd)
        _agl_str = f" · {_agl[0]} {_agl[1]}" if _agl else ''
        # v8.16.1 Bug-2b: reconcile an AUTO Mistake/Punt with the hand's own
        # action review. If the only postflop signal is the aggression label and
        # it shows ONLY correct/borderline play (no Missed/Too-aggressive marker),
        # the auto verdict has no corroborating action-level mistake → downgrade
        # to Review instead of asserting an unconfirmed Mistake (78024888). Never
        # touches analyst verdicts; preflop/no-label mistakes are left alone.
        _review_downgrade = False
        _orig_auto_label = ''
        if auto_verdict_needs_review(verdict, _is_auto_verdict,
                                     (_agl[1] if _agl else '')):
            _review_downgrade = True
            _orig_auto_label = _verdict_display_label(verdict) or 'Mistake'
            verdict = ''
            _is_auto_verdict = False
        # v8.14.1 P0-5: when an analyst graded this hand on a SPECIFIC street, the
        # auto aggression-gate header tag must not assert a DIFFERENT street
        # (73279283: detector "Missed turn aggression" vs analyst river-call
        # mistake). On a street conflict suppress the auto suffix — the analyst
        # verdict pill governs the header. Stamp the conflict so the body
        # aggression-gate note can demote itself to match.
        _agg_conflict = False
        if _agl and isinstance(cmt, dict) and cmt.get('verdict'):
            _AGL_STREETS = ('preflop', 'flop', 'turn', 'river')
            _ana_txt = (f"{cmt.get('key_decision','')} "
                        f"{cmt.get('street','')}").lower()
            _ana_str = next((s for s in _AGL_STREETS if s in _ana_txt), '')
            _agg_str = next((s for s in _AGL_STREETS
                             if s in (_agl[1] or '').lower()), '')
            if _ana_str and _agg_str and _ana_str != _agg_str:
                _agl_str = ''
                _agg_conflict = True
        # v8.8.5: tournament context tag
        _h_fmt = h.get('format', '')
        _fmt_pill = ''
        if _h_fmt == 'SATELLITE':
            _fmt_pill = ' <span class="context-pill satellite">Satellite</span>'
        elif _h_fmt == 'RACER':
            _fmt_pill = ' <span class="context-pill racer">Racer</span>'
        elif _h_fmt == 'MYSTERY_BOUNTY':
            _fmt_pill = ' <span class="context-pill mystery">Mystery</span>'
        # ICM caution for satellite/extreme ICM
        _icm_p = h.get('icm_pressure', 0) or 0
        if _h_fmt == 'SATELLITE' or _icm_p > 0.7:
            _fmt_pill += ' <span class="context-pill icm-caution" title="cEV-only; may be misleading in satellite / extreme ICM context">⚠️ ICM</span>'
        from gem_report_draft._helpers import short_verdict_pill as _svp
        if _review_downgrade:
            _vp = "<span class='verdict-pill' data-verdict='Review'>Review</span>"
        else:
            _vp = _svp(h, verdict, app_details)
        # v8.14.1 P0-4: for a preflop all-in the meaningful depth is the
        # EFFECTIVE stack vs the live opponent, not Hero's nominal stack. Show
        # both when they differ (e.g. SB 33.6BB jam into an 18BB BB).
        _eff_dec = h.get('eff_stack_bb_at_decision') or 0
        if h.get('pf_allin') and _eff_dec and _eff_dec < (stack_bb - 0.5):
            _stack_disp = f"{pos} {stack_bb:.1f}BB → eff {_eff_dec:.1f}BB"
        else:
            _stack_disp = f"{pos} {stack_bb:.1f}BB"
        doc.w(f"#### Hand `{hid_short}` — {_cards_str_to_pills(cards)} "
              f"({_stack_disp}) "
              f"· {bb_html}{_agl_str}{_fmt_pill}" + (f" {_vp}" if _vp else ""))
        doc.w("</div>")  # close mh-title
        doc.w("<div class='mh-actions'>")
        _emit_gtow_button(doc, h, app_details, hid_short, rd=rd)
        doc.w("</div>")
        doc.w("</div>")  # close mh-top
        doc.w("")

        # Verdict + backlinks on a single italic line.
        # B67/B75 (v7.56, Ron 2026-05-18): distinctive verdict emojis so each
        # verdict class is visually unique (not just thumbs-up clones):
        #   ❄️  I.7 Cooler            (frozen runout, unavoidable)
        #   ⚖️  III.0 GTO-Standard    (analyst confirmed GTO-standard play)
        #   👍  III.3 Cleared          (analyst confirmed standard play)
        #   👍  III.5 Justified        (deliberate +EV exploit)
        #   📖  III.4 Read-dependent   (verdict depends on read)
        #   👎  III.1 Punt             (clear mistake)
        verdict_emoji = ''
        # v8.12.12 (Obj-H): default to the code-stripped label so an unmapped
        # verdict never leaks "III.x"/"I.7" into the modal header.
        verdict_label = _verdict_display_label(verdict) or '—'
        if verdict.startswith('I.7'):
            verdict_emoji = '❄️'
            verdict_label = 'Cooler'
        elif verdict.startswith('III.0'):
            verdict_emoji = '⚖️'
            verdict_label = 'GTO-Standard'
            _oce, _oct = _outcome_label(cmt, default=('', ''))
            if _oce:
                verdict_emoji = _oce
                verdict_label = _oct
        elif verdict.startswith('III.1'):
            verdict_emoji = '👎'
            verdict_label = 'Punt'
        elif verdict.startswith('III.2'):
            verdict_emoji = '👎'
            verdict_label = 'Mistake'
        elif verdict.startswith('III.3'):
            verdict_emoji = '👍'
            verdict_label = 'Cleared'
            _oce, _oct = _outcome_label(cmt, default=('', ''))
            if _oce:
                verdict_emoji = _oce
                verdict_label = _oct
        elif verdict.startswith('III.4'):
            verdict_emoji = '📖'
            verdict_label = 'Read-Dependent'
        elif verdict.startswith('III.5'):
            verdict_emoji = '👍'
            verdict_label = 'Justified'
        elif verdict.startswith('III.8'):
            _arche = (cmt.get('archetype', '') or '').strip()
            verdict_emoji = '⭐'
            verdict_label = f"Pick — {_arche}" if _arche else 'Pick'
        # B-V10: strip S-prefix from backlinks — user sees "Coolers ↑" not "S1.7 Coolers ↑"
        backlinks = []
        if verdict.startswith('I.7'):
            backlinks.append('[Coolers ↑](#sec-1-7)')
        if verdict.startswith('III.0'):
            backlinks.append('[Cleared ↑](#sec-13-1)')
        if verdict.startswith('III.1'):
            backlinks.append('[Punts ↑](#sec-2-1)')
        if verdict.startswith('III.3'):
            backlinks.append('[Cleared ↑](#sec-13-1)')
        if verdict.startswith('III.4'):
            backlinks.append('[Read-Dep ↑](#sec-13-2)')
        if verdict.startswith('III.5'):
            backlinks.append('[Justified ↑](#sec-13-3)')
        if verdict.startswith('III.8'):
            backlinks.append("[Pokerbot's Picks ↑](#sec-4-3)")
        if (h.get('net_bb') or 0) < -25:
            backlinks.append('[Large Losses ↑](#sec-1-3)')
        if hid in review_hand_ids:
            backlinks.append('[Reviewed ↑](#sec-17-4-reviewed)')
        # F2 (v7.49): augment with actual citation-tracker entries (any section
        # that referenced this hand via _hand_ref during body emission).
        # Dedupe by anchor against the heuristic-based backlinks above.
        already_anchors = set()
        for bl in backlinks:
            # backlinks are markdown "[label ↑](#anchor)" — extract anchor
            if '#' in bl:
                anchor_id = bl.rsplit('#', 1)[-1].rstrip(')')
                already_anchors.add(anchor_id)
        for anchor, label in _state._get_citations_for(hid):
            if anchor in already_anchors:
                continue
            # Try to extract a short section number from label (e.g. "III.1 Range Oblivion" → "III.1")
            short_label = label.split(' — ')[0] if label else anchor
            short_label = short_label[:24].rstrip()
            backlinks.append(f'[{short_label} ↑](#{anchor})')
            already_anchors.add(anchor)
        _auto_badge = ' <span style="font-size:11px;color:#6b7280;border:1px solid #d1d5db;border-radius:8px;padding:1px 6px;margin-left:4px">auto</span>' if _is_auto_verdict else ''
        verdict_line = f"*Verdict:* {verdict_emoji} {verdict_label}{_auto_badge}"
        # Store explanation for yellow notes block BELOW the grid
        _xiva_why_content = None
        _xiva_why_street = ''
        if _review_downgrade:
            # v8.16.1 Bug-2b: explicit Review line — the auto Mistake/Punt was
            # not corroborated by the hand's own action review.
            _rv_badge = (' <span style="font-size:11px;color:#6b7280;border:1px '
                         'solid #d1d5db;border-radius:8px;padding:1px 6px;'
                         'margin-left:4px">auto</span>')
            _agl_ctx = f" ({_agl[0]} {_agl[1]})" if _agl else ''
            verdict_line = (f"*Verdict:* 🔍 Review{_rv_badge} — auto-flagged "
                            f"{_orig_auto_label}, but the hand's action review "
                            f"shows no clear mistake{_agl_ctx}; confirm manually.")
        elif not verdict:
            # B166 / B-A fix: no analyst verdict — show a neutral label above
            # the grid, and store the explanation for the yellow block below.
            _wf = _xivb_flag_note(hid, s, rd, h)
            if _wf:
                _ex = (_wf.get('explanation') or '').strip()
                _lb = _wf['label']
                if _ex.startswith(_lb):
                    _ex = _ex[len(_lb):].lstrip('. ').strip()
                _wx = f" — {_ex}" if _ex else ''
                # v8.8.6 S1: satellite caveat — inline into coaching text
                if _h_fmt == 'SATELLITE' or _icm_p > 0.7:
                    _ex = _ex.replace(
                        'folding it is the leak',
                        'folding it is the leak by chipEV — but satellite/ICM may make folding defensible')
                    _ex = _ex.replace(
                        'passing on it is the deviation',
                        'passing on it is the deviation by chipEV — satellite/ICM may override')
                    _wx = f" — {_ex}" if _ex else ''
                verdict_line = f"*Flagged:* {_wf['emoji']} {_lb}"
                _xiva_why_content = f"{_wf['emoji']} {_lb}{_wx}"
                _xiva_why_street = _street_attr(_wf.get('street') or '')
            else:
                _cz = _state._get_citations_for(hid)
                _anc, _lbl = (_cz[0] if _cz else ('', 'the report'))
                verdict_line = f"*Verdict:* ⚪ pending review"
                _xiva_why_content, _xiva_why_street = _why_here_text(_anc, _lbl)
                # Q5: enrich all-in hands with range commentary
                _q5_rng = _allin_range_note(h)
                if _q5_rng:
                    _xiva_why_content = (_xiva_why_content or '') + _q5_rng
                if not _xiva_why_street and 'viii-4' in (_anc or '').lower():
                    _cr_a = h.get('check_raises', [])
                    if _cr_a:
                        _xiva_why_street = _street_attr(_cr_a[0])
        # v8.8.6 S1: satellite / extreme-ICM caveat — display only, no verdict change
        if _h_fmt == 'SATELLITE' or _icm_p > 0.7:
            verdict_line += ' · ⚠️ *chipEV-only — satellite/ICM context may override*'
        # Phase 4.7 C3: mh-verdict / mh-links wrappers (v29 vocabulary)
        doc.w("<div class='mh-verdict'>")
        doc.w(verdict_line)
        if backlinks:
            _bl_chips = ' '.join(f'<span class="ie-wc">{_md_inline(bl)}</span>' for bl in backlinks)
            doc.w(f"<div class='mh-links'>{_bl_chips}</div>")
        doc.w("</div>")
        doc.w("")
        # B235 (Ron review 2026-05-25): the IV.6 solver note was previously a
        # loose line HERE, above the grid. Ron wants it in the yellow
        # analyst-notes block under the grid instead — it is now emitted by
        # _emit_agg_gate_block (below the hand grid). Nothing emitted here.

        # Ron 2026-05-11: compact metadata. Subtitle = tour + date + format.
        # Game-relevant line = pot-type + eff stack + SPR + result. Board
        # already shown at FLOP header. Opener position+size visible in
        # preflop action. Phase ("post_reg" / "ITM") usually adds no signal
        # for individual hand review.
        # Phase 4.5: compact metadata as chips (v27 spec §4)
        tname = h.get('tournament', '—')
        if len(tname) > 60:
            tname = tname[:58] + '…'
        fmt = h.get('format', '—')
        lvl = h.get('level', '—')
        # B-V10 (2026-06-01): prefer eff_stack_bb_at_decision for preflop
        # decisions (jams, CVJ) — eff_stack_bb is the flop-context value which
        # falls back to Hero's nominal stack when no flop was seen.
        eff = h.get('eff_stack_bb_at_decision') or h.get('eff_stack_bb') or 0
        pot_type = h.get('pot_type', '—')
        spr = h.get('spr')
        result_str = ('Won' if h.get('won') else 'Lost')
        if h.get('went_to_sd'):
            result_str += ' SD'
        _t_phase = (h.get('tournament_phase') or '').replace('_', ' ').strip()
        _chips = [tname, h.get('date', '—'), fmt, f"L{lvl}"]
        if _t_phase:
            _chips.append(_t_phase.title())
        _chips += [pot_type, f"Eff {eff:.1f}BB"]
        if spr is not None and (h.get('board') or []):
            _chips.append(f"SPR {spr:.1f}")
        _chips.append(result_str)
        # Item 16: III.1/III.2 hands get a mistake pill on the card header
        # Item 1: III.0 GTO-Standard gets a positive pill
        if verdict.startswith('III.0'):
            _chips.insert(0, '⚖️ GTO-Standard')
        elif verdict.startswith('III.1'):
            _chips.insert(0, '👎 Punt')
        elif verdict.startswith('III.2'):
            _chips.insert(0, '🔴 Mistake')
        # Phase 4.7 C3: mh-meta / mh-chip (v29 vocabulary)
        _chip_html = []
        for c in _chips:
            _extra = ''
            if c in ('👎 Punt', '🔴 Mistake'):
                _extra = ' bad'
            _chip_html.append(f"<span class='mh-chip{_extra}'>{c}</span>")
        doc.w("<div class='mh-meta'>" + ''.join(_chip_html) + "</div>")
        # B61 (v7.55, Ron 2026-05-18): *Showdown:* meta line removed.
        # Hero hand now shown via the hero-hand div above the grid,
        # and villain showdown cards appear in the grid's result footer row.
        # The legacy line was redundant.
        doc.w("")

        # v7.45 (Ron 2026-05-11): rich preflop action with stacks + bet sizes
        # + bounty-coverage hints + color hierarchy. Uses
        # rd['appendix_hand_details'][hid] populated in prepare_report_data.
        # (app_details already defined above for GTOW button)
        seats = app_details.get('seats') or []
        actions = (app_details.get('actions') or {}).get('preflop') or []
        is_bounty = app_details.get('is_bounty', False)
        hero_stack_chips = app_details.get('hero_stack_chips') or 0

        # Show table-level stack snapshot — but ONLY for the players who
        # actually participated. Pure folds in the preflop action are noise;
        # showing all 8 seats overwhelmed the reader (Ron 2026-05-11).
        # Rule: include Hero + anyone who called/bet/raised at any street.
        # Skip the whole block when NON-BOUNTY (no coverage info to convey)
        # AND only Hero acted alone — postflop carries the same stack info.
        if seats:
            all_actions_check = app_details.get('actions') or {}
            participants = set()
            for street_acts in all_actions_check.values():
                for a in street_acts:
                    if a.get('action') not in ('folds',):
                        participants.add(a.get('position'))
            participants.add(h.get('position', ''))  # Hero always shown
            seats_to_show = [s for s in seats if s.get('position') in participants]
            # Skip the whole block when only Hero acted (no information value)
            if len(seats_to_show) <= 1 and not is_bounty:
                pass
            else:
                # Phase 4.5: wrap stacks in collapsible disclosure (v27 spec §4)
                # Phase 4.7 C3: add modal-stack alongside stack-context (v29 vocabulary)
                doc.w(f"<details class='stack-context modal-stack'>")
                doc.w(f"<summary>Stack context ({'🎯 BOUNTY' if is_bounty else 'NON-BOUNTY'})</summary>")
                doc.w("")
                # v8.7.3: build villain read context lookup for stack table
                _vi_intel = s.get('villain_intel', {}) or {}
                _vi_aliases_st = _vi_intel.get('villain_aliases', {}) or {}
                _vi_reads_st = _vi_intel.get('read_states', {}) or {}
                _tid_st = h.get('tournament_id', '')

                doc.w("| Pos | Stack | vs Hero | Read Context |")
                doc.w("|---|---|---|---|")
                for seat in seats_to_show:
                    stack_bb_s = seat.get('stack_bb', 0)
                    if seat.get('is_hero'):
                        vs_str = '—'
                    elif is_bounty:
                        # v8.12.12 (Obj-F): compute cover direction + delta from
                        # the real chip stacks for EVERY villain, not the upstream
                        # hero_covers/covers_hero flags (only the BB seat was set;
                        # the rest collapsed to a misleading '= equal').
                        vs_str = _stack_cover_label(
                            hero_stack_chips, seat.get('stack_chips') or 0,
                            app_details.get('bb_size_chips'))
                    else:
                        diff = (seat["stack_chips"] - hero_stack_chips) / (app_details.get("bb_size_chips") or 1)
                        if diff > 0.1: vs_str = f'+{diff:.1f}BB'
                        elif diff < -0.1: vs_str = f'{diff:.1f}BB'
                        else: vs_str = '='
                    # v8.7.8: villain/read context column
                    # Seat 'name' is often the position label (BTN, SB), not the
                    # player hash. Look up actual player by position in villains dict.
                    _read_ctx = ''
                    if not seat.get('is_hero'):
                        _spos = seat.get('position', '')
                        _sname = ''
                        for _vn, _vi_seat in (h.get('villains') or {}).items():
                            if _vi_seat.get('position') == _spos:
                                _sname = _vn
                                break
                        if not _sname:
                            _sname = seat.get('name', '') or seat.get('player', '')
                        if _sname and _tid_st:
                            _svk = f'{_tid_st}|{_sname}'
                            _sva = _vi_aliases_st.get(_svk, {})
                            _srs = _vi_reads_st.get(_svk, {})
                            if _sva.get('alias'):
                                _salias = _sva['alias']
                                _svnum = _sva.get('v_number', '')
                                _sdisp = _salias if _salias == _svnum else f'{_salias} · {_svnum}'
                                _sread = _srs.get('primary_read', '')
                                _sn_ev = _sva.get('n_evidence', 0)
                                if _sread:
                                    _read_ctx = f'{_sdisp} · {_sread} · {_sn_ev} ev'
                                elif _sn_ev:
                                    _read_ctx = f'{_sdisp} · {_sn_ev} ev'
                                else:
                                    _read_ctx = _sdisp
                    if seat.get('is_hero'):
                        pos_disp = f"**{seat['position']} (Hero)**"
                    else:
                        pos_disp = seat['position']
                    doc.w(f"| {pos_disp} | {stack_bb_s:.1f}BB | {vs_str} | {_read_ctx} |")
                doc.w("")
                doc.w("</details>")

        # v7.45 (Ron 2026-05-11, item C): street-by-street hand walkthrough
        # with embedded analyst comments. Per street: card header → colored
        # action list → analyst note if relevant for this street, else 👍.
        all_actions = app_details.get('actions') or {}
        board = h.get('board') or []
        spr = h.get('spr')

        # Decide WHICH street the analyst commentary attaches to.
        # Heuristic: if cmt has a 'street' field, use it; else attach to the
        # street where Hero made the last meaningful (non-fold) action.
        analyst_street = (cmt.get('street') or '').lower()
        # v8.12.3 (Ron QA, hand 59114187): a note quoting the FULL runout
        # (e.g. **6-2-7-T-7**) must not land on an earlier street where those
        # cards have not been seen yet — route it to the last street Hero
        # acted on instead.
        if not analyst_street:
            import re as _re_fb
            _arg_fb = review_cmt.get('argument') or cmt.get('argument', '')
            if _re_fb.search(r'\*\*\w{1,2}(?:-\w{1,2}){3,4}\*\*', _arg_fb or ''):
                for _fb_st in ('river', 'turn'):
                    if any(a.get('is_hero')
                           for a in (all_actions.get(_fb_st) or [])):
                        analyst_street = _fb_st
                        break
        if not analyst_street:
            # Q1: parse key_decision + argument for street keywords before
            # falling back to action scan. Catches missed-value / missed-cbet
            # patterns where all postflop hero actions are checks and the old
            # heuristic fell through to preflop.
            import re as _re_q1
            _q1_text = ((cmt.get('key_decision') or '') + ' '
                        + (review_cmt.get('argument') or cmt.get('argument', ''))).lower()
            for _q1_st, _q1_kw in [
                ('river', r'\b(river|missed.{0,20}value.{0,10}bet)\b'),
                ('turn',  r'\bturn\b'),
                ('flop',  r'\b(flop|missed.{0,20}c-?bet)\b'),
            ]:
                if _re_q1.search(_q1_kw, _q1_text):
                    if any(a.get('is_hero') for a in (all_actions.get(_q1_st) or [])):
                        analyst_street = _q1_st
                        break
        if not analyst_street:
            # Find last hero non-fold action across streets
            for st in ('river', 'turn', 'flop', 'preflop'):
                for a in (all_actions.get(st) or []):
                    if a.get('is_hero') and a.get('action') not in ('folds', 'checks'):
                        analyst_street = st
                        break
                if analyst_street: break
        if not analyst_street:
            # Last resort: include checks — a river check IS a decision
            for st in ('river', 'turn', 'flop'):
                for a in (all_actions.get(st) or []):
                    if a.get('is_hero') and a.get('action') != 'folds':
                        analyst_street = st
                        break
                if analyst_street: break
        if not analyst_street:
            analyst_street = 'preflop'

        # Compose the analyst-notes block once — we'll attach it under the
        # right street. Pre-build the lines.
        argument = review_cmt.get('argument') or cmt.get('argument', '')
        # v8.14.1 P0-2: compute the chart-backed range evidence once for this
        # hand (reused for the block below). When a block will render, strip the
        # vague templated "### Range Logic — turns on whether ... is inside the
        # RFI core" boilerplate from the analyst argument: it is exactly the
        # "where is the range?" complaint, and the concrete evidence block now
        # supersedes it (also removes a hedged 'inside' that reads as a
        # contradiction when the chart says OUTSIDE).
        try:
            from gem_report_draft._helpers import hand_range_evidence as _hre_pre
            _rev_xiva = _hre_pre(h)
        except Exception:
            _rev_xiva = None
        if _rev_xiva and argument and '### Range Logic' in argument:
            import re as _re_rl
            argument = _re_rl.sub(
                r'\n*#{2,3}\s*Range Logic\b.*?(?=\n#{2,3}\s|\Z)',
                '\n', argument, flags=_re_rl.S).rstrip()
        # Item 17: warn on suspiciously short analyst argument (likely truncated)
        if argument and len(argument.strip()) < 30 and not argument.strip().startswith('**TL;DR:**'):
            import sys as _sys17
            print(f"  ⚠️  W-TRUNC: Hand {hid} analyst argument is only "
                  f"{len(argument.strip())} chars — possibly truncated: "
                  f"'{argument.strip()[:50]}'", file=_sys17.stderr)
        key_dec = cmt.get('key_decision', '')
        one_two = cmt.get('one_two_back', '')
        matchup = cmt.get('matchup_math', '')
        spot = cmt.get('spot', '')
        has_analyst = bool(argument or key_dec or one_two or matchup or spot)

        # Ron 2026-05-11: split argument prose per-street so each street gets
        # ONLY its relevant commentary. Heuristic: sentences starting with
        # street keywords ("preflop", "flop", "turn", "river") route to that
        # street. Remaining sentences (general framing / math / pop reads)
        # route to the key-decision street (last non-fold hero action).
        import re as _re_split
        _street_kw = {
            'preflop': r'(?:pre-?\s*flop|preflop|pf\b|pre\s)',
            'flop':    r'(?:flop\b|flop[\s,.])',
            'turn':    r'(?:turn\b|turn[\s,.])',
            'river':   r'(?:river\b|river[\s,.])',
        }
        sentences = _re_split.split(r'(?<=[.!?])\s+(?=[A-Z(])',
                                     argument.strip()) if argument else []
        sentences = [sn.strip() for sn in sentences if sn.strip()]
        per_street = {'preflop': [], 'flop': [], 'turn': [], 'river': []}
        general = []
        for sn in sentences:
            sn_low = sn.lower()
            matched = None
            # Test first 25 chars for street keyword (early-sentence anchor)
            prefix = sn_low[:30]
            for street, kw in _street_kw.items():
                if _re_split.search(r'^[\s\W]*' + kw, prefix):
                    matched = street
                    break
            if matched:
                per_street[matched].append(sn)
            else:
                general.append(sn)
        # Identify key-decision street (where general sentences go)
        # = analyst_street (computed earlier from last non-fold hero action)
        per_street[analyst_street].extend(general)

        def _emit_street_analyst(street):
            """Emit analyst commentary specific to one street, concise per street."""
            stmts = per_street.get(street, [])
            if not stmts: return
            # For the KEY-DECISION street, also include spot/key_decision/matchup
            extras_for_key = (street == analyst_street)
            doc.w("⚠️ **Analyst:**")
            if extras_for_key and spot:
                doc.w(f"*Spot:* {spot}")
            for sn in stmts:
                doc.w(sn)
            if extras_for_key and key_dec and key_dec not in argument:
                doc.w(_break_at_sentences(key_dec, prefix='*Key decision:*'))
            if extras_for_key and matchup and matchup not in argument:
                doc.w(_break_at_sentences(matchup, prefix='*Math:*'))
            if extras_for_key and one_two and one_two not in argument:
                doc.w(_break_at_sentences(one_two, prefix='*1-2 back:*'))
            doc.w("")

        # Fallback for hands with no street-routable prose: emit everything
        # under the key-decision street, as before.
        no_routable = all(not per_street[st] for st in per_street)
        def _emit_analyst_fallback():
            if not has_analyst: return
            doc.w("⚠️ **Analyst:**")
            doc.w("")
            if spot:
                doc.w(f"*Spot:* {spot}")
                doc.w("")
            if argument:
                doc.w(_break_at_sentences(argument, prefix='*Why:*'))
                doc.w("")
            if key_dec:
                doc.w(_break_at_sentences(key_dec, prefix='*Key decision:*'))
                doc.w("")
            if one_two:
                doc.w(_break_at_sentences(one_two, prefix='*1-2 actions back:*'))
                doc.w("")
            if matchup:
                doc.w(_break_at_sentences(matchup, prefix='*Matchup math:*'))
                doc.w("")

        # PREFLOP
        # B48 (v7.53, Ron 2026-05-18): replaced verbose per-street prose with
        # visual hand grid. The grid renders all streets in a single horizontal
        # table (GG/GTOW-style) with color-coded actions, hero highlighting,
        # and numbered (1)/(2)/(3) annotations referencing the notes block.
        # F1 (v7.49): compute pot in BB at each street start for inline display
        pot_by_street = _compute_pot_by_street(all_actions, h)

        # Bug 2 lint (Ron 2026-05-30): cross-check analyst prose pot claims
        # against reconstructed street pots. The analyst sometimes writes
        # "jam X BB into ~N BB" with an incorrect pot figure (e.g. turn pot
        # instead of river pot). Warn on mismatch > 30%.
        if argument:
            import re as _re_pot
            # Match patterns like "into ~6 BB", "into ~12.5 BB", "into 8BB"
            _pot_claims = _re_pot.findall(
                r'into\s+~?\s*(\d+(?:\.\d+)?)\s*BB', argument, _re_pot.IGNORECASE)
            if _pot_claims:
                # Determine the relevant street — use the analyst_street or last
                # street with actions.
                _check_street = analyst_street or 'river'
                _actual_pot = pot_by_street.get(_check_street, 0)
                # If analyst_street pot is 0, try each street in reverse
                if _actual_pot == 0:
                    for _cs in ('river', 'turn', 'flop', 'preflop'):
                        if pot_by_street.get(_cs, 0) > 0:
                            _actual_pot = pot_by_street[_cs]
                            _check_street = _cs
                            break
                if _actual_pot > 0:
                    # v8.12.4 (QA item 29): the linter compared every claim
                    # against the STREET-START pot — "call X into Y" quotes
                    # the pot AT THE DECISION. v8.12.6 (Chat session
                    # 2026-06-11, TM6065656465): a multi-street argument
                    # quotes one pot PER STREET ("6.7 into 13.5" flop,
                    # "20.2 into 27" turn) but every token was checked
                    # against the single analyst_street — the flop figure
                    # warned at 43% drift against the TURN pot. A claim now
                    # passes if it fits ANY street's [0.7x start, 1.3x end]
                    # window; only figures matching NO street at all warn.
                    _so_pot = ['preflop', 'flop', 'turn', 'river']
                    _windows_pot = []
                    for _wi, _ws in enumerate(_so_pot):
                        _wstart = pot_by_street.get(_ws, 0)
                        if _wstart <= 0:
                            continue
                        _wend = 0
                        for _ns_pot in _so_pot[_wi + 1:]:
                            if pot_by_street.get(_ns_pot, 0) > 0:
                                _wend = pot_by_street[_ns_pot]
                                break
                        _whi = max(_wstart, _wend, (h.get('total_pot_bb') or 0)
                                   if _ws == _so_pot[-1] else _wend or _wstart)
                        _windows_pot.append((_ws, _wstart, _whi))
                    # v8.13.1 P2: also accept the hand's _pot_odds per-street
                    # pots ("call X into Y" quotes the pot AT THE DECISION).
                    _po_block_wp = ((rd.get('pot_odds_by_hand') or {}).get(hid)
                                    or (rd.get('pot_odds_by_hand') or {}).get(
                                        (hid[-8:] if hid else hid)))
                    for _claim_str in _pot_claims:
                        _claimed = float(_claim_str)
                        if _claimed <= 0:
                            continue
                        if _wpot_claim_ok(_claimed, _po_block_wp, _windows_pot):
                            continue
                        _drift = abs(_claimed - _actual_pot) / _actual_pot
                        if _drift > 0.30:
                            import sys as _sys_pot
                            _wins_str = ', '.join(
                                f"{_ws2} {_wlo:.1f}-{_whi2:.1f}"
                                for _ws2, _wlo, _whi2 in _windows_pot)
                            print(
                                f"  ⚠️  W-POT: Hand {hid} analyst "
                                f"argument claims pot ~{_claimed:.1f} BB "
                                f"but it matches no street window or pot-odds "
                                f"pot ({_wins_str})",
                                file=_sys_pot.stderr)

        # Build hero-actions-by-street mapping
        hero_actions_by_street = _hero_actions_by_street_from_app(app_details)
        # Build numbered notes (B57 returns tone too)
        # B108 (v7.59, Ron 2026-05-19): pass analyst_street so explicit
        # cmt['street'] overrides the last-non-fold heuristic.
        _hero_verbs_a = _hero_action_verbs_by_street_from_app(app_details)
        notes, action_to_note_num, action_to_tone, single_narrative_note_num = \
            _split_argument_into_notes(
            argument, key_dec, one_two, matchup, spot,
            hero_actions_by_street, analyst_street=analyst_street,
            hero_action_verbs_by_street=_hero_verbs_a
        )
        # If no analyst argument produced notes, try aggression gate commentary
        # so the grid still gets 👍 on clean actions and (N) on flagged ones.
        if not notes and not argument:
            _agg_cands_a = _agg_candidates(h.get('id') or hid_short, rd)
            if _agg_cands_a:
                _agg_parts_a = []
                _agg_st_a = None
                for _ac_a in _agg_cands_a:
                    _ae_a, _al_a = _agg_one_label(_ac_a)
                    _st_a = _ac_a.get('street_of_interest', '')
                    if not _agg_st_a:
                        _agg_st_a = _st_a
                    _agg_parts_a.append(f"{_st_a.capitalize()}: {_ae_a} {_al_a}. "
                                        f"{_agg_commentary(_ac_a)}")
                notes, action_to_note_num, action_to_tone, single_narrative_note_num = \
                    _split_argument_into_notes(
                    ' '.join(_agg_parts_a), '', '', '', '',
                    hero_actions_by_street, analyst_street=_agg_st_a,
                    hero_action_verbs_by_street=_hero_verbs_a)
        # B156: if no notes at all and verdict is III.3/III.5/I.7, add a positive marker
        if not notes and verdict in ('III.3 Cleared', 'III.5 Justified', 'I.7 Cooler'):
            _pos_label = '✓ Standard line' if 'III.3' in verdict else ('✓ Justified' if 'III.5' in verdict else '✓ Cooler — no fold')
            notes = {1: _pos_label}
            action_to_tone = {}
            single_narrative_note_num = 1

        # Determine which streets have meaningful content
        used_streets = []
        for street in ('preflop', 'flop', 'turn', 'river'):
            st_actions_list = all_actions.get(street) or []
            cards = _street_cards(board, street)
            if st_actions_list or cards:
                used_streets.append(street)
        if not used_streets and h.get('pf_sequence'):
            used_streets = ['preflop']

        # Item 12b: always show hero cards + position, even for preflop-only/no-board hands
        hero_cards_list = h.get('cards') or []
        if hero_cards_list:
            hero_cards_html = _cards_html(hero_cards_list, sort_desc=True)
            pos = h.get('position', '?')
            pos_suffix = f" <span class='hero-pos'>in the {pos}</span>" if pos != '?' else ''
            _nick = nickname_for(hero_cards_list)
            nick_html = f" <span class='hero-nick'>{_nick}</span>" if _nick else ''
            # B246 (Ron review 2026-05-26): tournament phase next to the
            # nickname — context for how the spot should be read (ICM etc.).
            _phase = (h.get('tournament_phase') or '').replace('_', ' ').strip()
            phase_html = (f" <span class='hero-phase'>· {_phase.title()}</span>"
                          if _phase else '')
            doc.w(f"<div class='hero-hand'><span class='label'>Hero:</span> "
                  f"<span class='cards'>{hero_cards_html}</span>"
                  f"{pos_suffix}{nick_html}{phase_html}</div>")
            # B246: opponent stacks at the decision — crucial for reading
            # an all-in (who covers whom, who is short). stacks_behind maps
            # the other live seats to their BB count.
            _sb = h.get('stacks_behind') or {}
            if isinstance(_sb, dict) and _sb:
                _stk = ' · '.join(f"{p} {v:.1f}BB" for p, v in _sb.items())
                doc.w(f"<div class='table-stacks'><span class='label'>"
                      f"Table:</span> Hero {h.get('stack_bb',0):.1f}BB "
                      f"· {_stk}</div>")
            doc.w("")

        if used_streets and (any((all_actions.get(s) or []) for s in used_streets)):
            _vb = _build_villain_badges(hid, s)   # full hid — atoms_by_hand keyed by full form
            _render_hand_grid_table(doc, h, app_details, board, notes,
                                     action_to_note_num, pot_by_street, used_streets,
                                     rd=rd, action_to_tone=action_to_tone,
                                     single_narrative_note_num=single_narrative_note_num,
                                     villain_badges=_vb)
            # v8.12.8 (QA G): lint analyst sizing claims against the
            # RENDERED action percentages (collected by the grid walk into
            # h['_grid_bet_pcts']) + flag notes filed under one street that
            # describe a later street's action. stderr only — same channel
            # as W-POT; the analyst pass fixes the prose, not the renderer.
            if argument:
                import re as _re_pct
                import sys as _sys_pct
                _grid_pcts = h.get('_grid_bet_pcts') or {}
                _claims = _re_pct.findall(
                    r'(?:bet|bets|lead|leads|barrel|barrels|jam|jams|raise'
                    r'|raises|x/r|check-raise[sd]?)\s+(?:the\s+)?'
                    r'(flop|turn|river)?\s*~?(\d{1,3})\s*%',
                    argument, _re_pct.IGNORECASE)
                for _cl_st, _cl_pct in _claims:
                    _cl_v = int(_cl_pct)
                    _sts = ([_cl_st.lower()] if _cl_st
                            else list(_grid_pcts.keys()))
                    _rendered = [p for _s3 in _sts
                                 for p in _grid_pcts.get(_s3, [])]
                    if _rendered and not any(abs(_cl_v - p) <= 2
                                             for p in _rendered):
                        print(f"  ⚠️  W-PCT: Hand {hid} analyst claims "
                              f"{_cl_v}% ({_cl_st or 'street?'}) but the "
                              f"rendered sizings are "
                              f"{ {k: v for k, v in _grid_pcts.items()} }",
                              file=_sys_pct.stderr)
                _so_ns = ['preflop', 'flop', 'turn', 'river']
                _n2s = {}
                for (_ns_st, _ns_i), _ns_num in (action_to_note_num
                                                 or {}).items():
                    _n2s.setdefault(_ns_num, _ns_st)
                for _ns_num, _ns_txt in enumerate(notes or [], 1):
                    _anchor = _n2s.get(_ns_num)
                    if _anchor not in _so_ns:
                        continue
                    _m_later = _re_pct.search(
                        r'\b(?:bet|bets|lead|leads|jam|jams|raise|raises'
                        r'|call|calls|check|checks)[a-z-]*\s+(?:the\s+)?'
                        r'(turn|river)\b', str(_ns_txt), _re_pct.IGNORECASE)
                    if _m_later:
                        _desc = _m_later.group(1).lower()
                        if (_so_ns.index(_desc)
                                > _so_ns.index(_anchor)):
                            print(f"  ⚠️  W-NOTE-STREET: Hand {hid} note "
                                  f"({_ns_num}) is anchored on {_anchor} "
                                  f"but describes the {_desc} — split the "
                                  f"note or re-anchor it",
                                  file=_sys_pct.stderr)
            # v8.8.6 VH Phase 4: yellow street notes for villain
            # coaching — v8.12.8 QA2: factored into the shared helper so
            # XIV.B stubs emit the same block (badge/note pairing).
            _emit_villain_street_notes(doc, s, hid, hid_short)
        elif h.get('pf_sequence'):
            # Fallback: legacy pf_sequence-only path (no full action stream)
            doc.w("**PREFLOP**")
            doc.w("")
            for step in h.get('pf_sequence', []):
                marker = '→ ' if '(H)' in step else '  '
                doc.w(f"{marker}`{step}`")
            doc.w("")
            if has_analyst:
                _emit_analyst_fallback()

        # FLOP / TURN / RIVER walk removed in v7.53 B48 — the visual hand grid
        # above now renders all streets together. Catch-all fallback below
        # preserves analyst notes that didn't route to any street.

        # Catch-all: if analyst notes exist but didn't get attached
        if has_analyst and not notes:
            _emit_analyst_fallback()

        # Item 12a: if MDA flag exists, surface the recommendation in the body
        # so the reader sees WHAT the MDA recommendation was (not just the pill).
        _mda_flag = _xivb_flag_note(hid, s, rd, h)
        if _mda_flag and 'MDA' in _mda_flag.get('label', ''):
            _mda_expl = _mda_flag.get('explanation', '')
            # v8.8.6 S1-fix: satellite caveat — inline into MDA coaching text
            if _mda_expl and (_h_fmt == 'SATELLITE' or _icm_p > 0.7):
                _mda_expl = _mda_expl.replace(
                    'folding it is the leak',
                    'folding it is the leak by chipEV — but satellite/ICM may make folding defensible'
                ).replace(
                    'passing on it is the deviation',
                    'passing on it is the deviation by chipEV — satellite/ICM may override')
            if _mda_expl:
                _ds_attr = _street_attr(_mda_flag.get('street'))
                _ds_tag = f" data-street='{_ds_attr}'" if _ds_attr else ''
                doc.w(f"<div class='analyst-notes'{_ds_tag}><p>{_mda_flag['emoji']} "
                      f"<strong>{_mda_flag['label']}:</strong> {_mda_expl}</p></div>")
                doc.w("")

        # B-A fix: emit the "why here" explanation in yellow notes BELOW the grid
        if _xiva_why_content:
            _xiva_ds = f" data-street='{_xiva_why_street}'" if _xiva_why_street else ''
            doc.w(f"<div class='analyst-notes'{_xiva_ds}>")
            doc.w(_xiva_why_content)
            doc.w("</div>")
            doc.w("")

        # B173 (Ron 2026-05-24): aggression-gate commentary in the yellow block
        # below the hand, not as a loose line above it.
        # v8.14.1 P0-5: skip the auto aggression-gate note when it grades a
        # DIFFERENT street than the analyst verdict (it would contradict the
        # analyst critique — e.g. detector "missed turn value-bet" beneath an
        # analyst river-call mistake). The analyst notes block already covers
        # the graded decision.
        if not locals().get('_agg_conflict'):
            _emit_agg_gate_block(doc, h.get('id') or hid_short, rd, hand=h)

        # v8.17.1 P1 (§9 capsule de-gate): the register-classified DECISION
        # capsule is the LEAD of this hand's commentary and is built for EVERY
        # scored/evidenced hand — NOT only hands that carry a pot-odds object
        # (the v8.17.0 regression: capsule lived inside `if _po:` → ~1% coverage).
        # _po (pot odds) is now ONE optional Math anchor. A capsule emits only
        # when it has a visible anchor (Range / Math / Exploit) OR a gradable
        # decision label (so no_clear_lesson can name the gap); otherwise it falls
        # through to the existing notes (zero-drop). The detailed notes (range
        # block, _po lines, villain notes) all still render BELOW this lead.
        try:
            from gem_commentary_capsule import (
                decision_capsule_from_signals as _dcs_lead,
                render_capsule_md as _rcm_lead)
            from gem_review_trust import (classify_preflop_allin as _cpa_lead,
                                          allin_kind_label as _akl_lead,
                                          multiway_render_plan as _mwp_lead)
            _po_lead = ((rd.get('pot_odds_by_hand') or {}).get(hid)
                        or (rd.get('pot_odds_by_hand') or {}).get(hid_short) or {})
            _rev_lead = locals().get('_rev_xiva') or {}
            _capdec_lead = ''
            if h.get('pf_allin'):
                _kc_lead = _cpa_lead(h)[0]
                if _kc_lead != 'not_allin':
                    _capdec_lead = _akl_lead(_kc_lead)
            # Range line: the canonical membership (single source of truth; the
            # full proxy/closest coverage is disclosed by the range block below).
            _rng_lead = ''
            if (_rev_lead.get('hero_hand')
                    and _rev_lead.get('membership') in ('inside', 'outside')):
                _ck_lead = (_rev_lead.get('chart_key')
                            or _rev_lead.get('spot_label') or 'range')
                _rng_lead = '%s %s %s' % (
                    _rev_lead['hero_hand'],
                    'inside' if _rev_lead['membership'] == 'inside' else 'outside',
                    _ck_lead)
            _mwp_l = {'suppress_hu_required_equity': False}
            if _po_lead:
                try:
                    _mwp_l = _mwp_lead(
                        n_live_opponents=max(0, (_po_lead.get('n_players_at_showdown') or 0) - 1),
                        players_still_to_act=_po_lead.get('players_still_to_act', 0) or 0)
                except Exception:
                    pass
            _why_lead = ((rd.get('analyst_commentary') or {}).get(hid, {})
                         or {}).get('hand_strength', '')
            _cap_lead = _dcs_lead(
                (_po_lead.get('street') if _po_lead else None)
                    or (h.get('hero_decision_street') or '').lower() or 'preflop',
                decision_label=_capdec_lead,
                verdict_hint=_po_lead.get('verdict_hint', '') if _po_lead else '',
                analyst_why=_why_lead,
                required_eq_pct=_po_lead.get('required_eq_pct') if _po_lead else None,
                multiway_suppressed=bool(_mwp_l.get('suppress_hu_required_equity')),
                range_line=_rng_lead)
            # Emit only with a real anchor OR a gradable decision (no_clear_lesson
            # names the gap). Never a bare no-anchor capsule on a non-decision hand.
            if _cap_lead and (_cap_lead.get('has_anchor') or _capdec_lead):
                _cs_lead = _street_attr(_cap_lead.get('street'))
                _ds_lead = f" data-street='{_cs_lead}'" if _cs_lead else ''
                doc.w(f"<div class='analyst-notes pb-capsule pb-cap-{_cap_lead['register']}'{_ds_lead}>")
                doc.w(_rcm_lead(_cap_lead))
                doc.w("</div>")
                doc.w("")
                h['_pb_capsule_emitted'] = True
        except Exception:
            pass

        # v8.14.1 P0-2: chart-backed Range evidence block. Any preflop range
        # claim (RFI / open-shove / call-jam / re-jam) gets a visible block whose
        # IN/OUTSIDE line is the SINGLE SOURCE OF TRUTH (real chart cells; proxy
        # /closest coverage disclosed). Contradiction guard: when the chart says
        # OUTSIDE but the analyst prose still claims inside/standard, emit a
        # W-RANGE-CONTRADICT lint (the prose itself is corrected in the data).
        try:
            from gem_report_draft._helpers import range_evidence_md as _rem
            _rev = locals().get('_rev_xiva')
            if _rev:
                doc.w("")
                doc.w(_rem(_rev))
                # Backstop lint: fire only on an ASSERTIVE inside/standard
                # membership claim that survives the data corrections + the
                # Range-Logic boilerplate strip (hedged "turns on whether ...
                # inside" is excluded). The block is authoritative regardless.
                if (_rev.get('chart_key')
                        and _rev.get('membership') == 'outside'
                        and isinstance(cmt, dict)):
                    _argl = (f"{cmt.get('argument','')} "
                             f"{cmt.get('key_decision','')} "
                             f"{cmt.get('spot','')}").lower()
                    _assertive_inside = ('is inside', 'is **inside**', '**inside** the',
                                         'sits inside', 'is in range', 'in the core range',
                                         'is a standard open', 'inside the standard',
                                         'inside the push range', 'inside the jam',
                                         # v8.14.1 REV3 (72807313/72807590 class): a chart
                                         # MEMBERSHIP claim beside an OUTSIDE chart.
                                         'inside this chart')
                    # v8.14.1 (GPT rev): also flag a "get-in" JUSTIFICATION asserted
                    # beside an OUTSIDE chart — an outside-chart jam must not read as a
                    # "standard get-in" / "correct push" without decision-time logic
                    # (73279700, 73720606). These are unambiguous claims; "outside
                    # standard jam range" prose does NOT contain them.
                    # v8.14.1 REV3: also flag chart-STATUS claims (range-standard /
                    # standard line / clean-by-chart / chart-approved) beside an OUTSIDE
                    # chart (72807313). Honest "outside chart but cleared on EV/fold-
                    # equity/exploit grounds" prose does NOT contain these tokens.
                    _assertive_getin = ('standard get-in', 'correct get-in',
                                        'justified get-in', 'correct push',
                                        'range-standard', 'standard line',
                                        'jam is clean', 'clean by chart',
                                        'chart-approved', 'chart approved')
                    _inside_hit = (any(w in _argl for w in _assertive_inside)
                                   and 'whether' not in _argl.split('inside')[0][-40:])
                    _getin_hit = any(w in _argl for w in _assertive_getin)
                    if _inside_hit or _getin_hit:
                        import sys as _sys_rc
                        print(f"  W-RANGE-CONTRADICT: {hid_short} analyst prose asserts "
                              f"inside/standard-get-in but chart shows "
                              f"{_rev['hero_hand']} OUTSIDE {_rev['chart_key']}",
                              file=_sys_rc.stderr)
                # v8.14.1 REV5 (72692569): a chart-EXISTENCE denial ("no rejam
                # chart" / "no chart for this matchup") must never sit beside a
                # canonical Range-evidence block that HAS a Reference + IN/OUTSIDE
                # membership. (The block's own "no exact chart at NBB" closest-
                # depth disclosure is NOT a denial and is not matched here.)
                if (_rev.get('chart_key')
                        and _rev.get('membership') in ('inside', 'outside')
                        and isinstance(cmt, dict)):
                    _argl_ce = (f"{cmt.get('argument','')} "
                                f"{cmt.get('key_decision','')} "
                                f"{cmt.get('spot','')}").lower()
                    if ('no rejam chart' in _argl_ce
                            or 'no chart for this matchup' in _argl_ce):
                        import sys as _sys_ce
                        print(f"  W-RANGE-CHART-EXISTS: {hid_short} prose claims 'no "
                              f"chart' but canonical Range evidence has Reference "
                              f"{_rev['chart_key']} ({_rev['membership']})",
                              file=_sys_ce.stderr)
                # v8.14.1 REV6 (73559949): the inverse — when canonical evidence has
                # NO charted range (chart_key absent, coverage 'none'), the prose may
                # NOT claim chart support ("inside the push range" / "inside the EP jam
                # range" / "clear push" / "standard shove" / "mandatory" / "range-
                # standard"). A proxy/closest block HAS a chart_key (its "no exact
                # chart at NBB; using nearest chart" disclosure is legitimate and is
                # NOT matched here, because chart_key is present).
                if (not _rev.get('chart_key')
                        and (_rev.get('coverage') in (None, 'none'))
                        and isinstance(cmt, dict)):
                    _argl_nc = (f"{cmt.get('argument','')} "
                                f"{cmt.get('key_decision','')} "
                                f"{cmt.get('spot','')}").lower()
                    _no_chart_support = ('inside the push range', 'inside the ep jam range',
                                         'inside the ep push range', 'inside the jam range',
                                         'inside the jamming range', 'clear push',
                                         'standard shove', 'mandatory', 'range-standard')
                    _nc_hit = [w for w in _no_chart_support if w in _argl_nc]
                    if _nc_hit:
                        import sys as _sys_nc
                        print(f"  W-RANGE-NO-CHART: {hid_short} prose claims chart "
                              f"support {_nc_hit} but canonical Range evidence has NO "
                              f"charted range ({_rev.get('spot_label','?')})",
                              file=_sys_nc.stderr)
        except Exception:
            pass

        # BUG-12 (Ron review 2026-05-31): surface pot-odds + bounty-adjusted
        # equity in the hand detail when computed.
        _po = (rd.get('pot_odds_by_hand') or {}).get(hid) or \
              (rd.get('pot_odds_by_hand') or {}).get(hid_short)
        if _po:
            _po_lines = []
            _po_lines.append(f"**Pot odds:** {_po.get('pot_odds', '\u2014')} "
                             f"(call {_po.get('call_bb', '\u2014')}BB into "
                             f"{_po.get('pot_before_call_bb', '\u2014')}BB)")
            # v8.16.4 DTI Blocker 2: the SAME structurally-provable all-in
            # decision-kind label the compact path carries, on the XIV.A full
            # card too (same _po object family / same hand fields, no recompute).
            # Unprovable -> "All-in decision (exact node type unavailable)".
            try:
                from gem_review_trust import (classify_preflop_allin as _cpa_a,
                                              allin_kind_label as _akl_a)
                if h.get('pf_allin'):
                    _k_a = _cpa_a(h)[0]
                    if _k_a != 'not_allin':
                        _po_lines.append("**Decision:** " + _akl_a(_k_a))
            except Exception:
                pass
            # v8.16.4 Obj 8: a multiway all-in is NOT a heads-up spot. Suppress the
            # single heads-up "Required equity" threshold (valid only vs one
            # villain) and frame the decision against the FIELD; flag uncertainty
            # when players are still to act. Uses the existing showdown-count
            # signal only \u2014 no equity/pot recompute.
            try:
                from gem_review_trust import multiway_render_plan as _mw_render_plan
                _mw_plan = _mw_render_plan(
                    n_live_opponents=max(0, (_po.get('n_players_at_showdown') or 0) - 1),
                    players_still_to_act=_po.get('players_still_to_act', 0) or 0)
            except Exception:
                _mw_plan = {'suppress_hu_required_equity': False,
                            'pot_odds_uncertain': False, 'label': ''}
            # v8.17.1 P1: the \u00a79 decision-capsule LEAD now renders ABOVE this
            # block (de-gated from `if _po:` so it covers every scored/evidenced
            # hand, not only pot-odds hands). Here _po only contributes the
            # detailed Math notes below; the capsule was already emitted as the lead.
            if not _mw_plan.get('suppress_hu_required_equity'):
                _po_lines.append(f"**Required equity:** {_po.get('required_eq_pct', '\u2014')}%")
                # v8.12.8 QA3: side-pot-aware price carries its basis
                if _po.get('required_eq_note'):
                    _po_lines.append(f"*({_po['required_eq_note']})*")
                # v8.14.1 hotfix (#73281169): teach what required equity MEANS \u2014
                # equity vs the betting/jamming range (incl. draws + worse hands),
                # NOT "how often you are ahead right now" (the user's exact question).
                if _po.get('required_eq_pct') not in (None, '\u2014'):
                    _po_lines.append(
                        "*This is the share you need to win versus the betting/"
                        "jamming range (including draws and worse hands) to break "
                        "even \u2014 not how often you are ahead right now.*")
            else:
                _po_lines.append(
                    f"**{_mw_plan.get('label') or 'Multiway all-in'}** \u2014 heads-up "
                    "required equity is not shown here; compare your equity to the "
                    "FIELD (all live opponents), not a single villain."
                    + ("" if not _mw_plan.get('pot_odds_uncertain')
                       else " Players are still to act, so the final pot odds are uncertain."))
            # v8.12.8: non-all-in calldown block \u2014 per-street lines with
            # the OVERBET flag (handover Issue 1)
            if _po.get('mode') == 'street_calls':
                if _po.get('is_overbet'):
                    _po_lines.append(
                        f"**OVERBET {_po.get('bet_pct_of_pot', 0):.0f}% pot** "
                        "\u2014 required equity is past where draws continue")
                for _scl in _po.get('per_street_summary') or []:
                    _po_lines.append(f"\u00b7 {_scl}")
            _n_sd = _po.get('n_players_at_showdown') or 0
            _mw_tag = f" *(multiway \u2014 {_n_sd} players)*" if _n_sd > 2 else ''
            _eq = _po.get('hero_equity_pct')
            if _eq is not None:
                _eq_mode = _po.get('equity_mode', '\u2014')
                _eq_label = ('Hero equity vs shown hand'
                             if _eq_mode == 'exact_vs_shown'
                             else 'Hero equity vs range')
                _po_lines.append(f"**{_eq_label}:** {_eq:.1f}% "
                                 f"({_eq_mode}){_mw_tag}")
            _vr = _po.get('villain_range_spec')
            if _vr:
                _po_lines.append(f"**Villain range:** {_vr}")
            _re = _po.get('realized_equity_vs_shown')
            if _re is not None:
                _po_lines.append(f"*Realized vs shown:* {_re:.1f}% *(result-derived)*")
            if _po.get('bounty'):
                # v8.12.12 (Obj-G): PKO bounty-adjusted threshold math, shown
                # ONLY where the cover status + estimate are known and the math
                # is safe. Collectibility comes from hero_covers_field (the same
                # real-stack signal the cover table now uses); the bounty value
                # and discount are MODEL estimates and are labelled as such.
                # Unknown / mystery / multiway / side-pot-unsafe spots never get
                # a numeric verdict \u2014 they degrade to an explicit "review
                # manually" cue instead of fabricated precision.
                _bnt = _po['bounty']
                _btype = _bnt.get('bounty_type')
                _covers = _po.get('hero_covers_field')
                _req_b = _po.get('required_eq_bounty_pct')
                _vbb = _bnt.get('value_bb') or 0
                _caveat = _po.get('bounty_caveat')
                # Skip the whole block for a pure freezeout (no bounty to model).
                if (_btype not in (None, 'none')) or _req_b is not None \
                        or _vbb > 0 or _caveat:
                    # Estimated bounty value. value_bb is 0 unless Hero covers,
                    # so this only shows for a collectible bounty. Show the real
                    # dollar figure as "$X \u2248 YBB" when a SAFE one exists in the
                    # export; otherwise state the dollar value is unavailable and
                    # fall back to the BB model estimate (never fabricate a $).
                    if _vbb > 0:
                        _usd = _pko_bounty_usd(rd, h)
                        if _usd:
                            _po_lines.append(
                                f"**Estimated bounty:** ${_usd:,.2f} \u2248 "
                                f"{_vbb:.1f}BB *(estimated bounty model)*")
                        else:
                            # v8.16.4 Obj 9: label the BB estimate's PROVENANCE
                            # explicitly (a flat event-level estimate is never
                            # shown as a per-decision dynamic value) and drop the
                            # internal method token from user text (Obj 3). Reuses
                            # the same _bnt fields (one source, no recompute).
                            try:
                                from gem_review_trust import bounty_provenance_label as _bpl2
                                _meth2 = str(_bnt.get('method') or 'flat_table')
                                _pkind2 = ('effective_bb' if 'effective' in _meth2
                                           else 'starting_bb_flat')
                                _po_lines.append("**" + _bpl2(_pkind2, value_bb=round(_vbb, 1)) + "**")
                            except Exception:
                                _po_lines.append(
                                    f"**Estimated bounty value:** \u2248 {_vbb:.1f}BB")
                            _po_lines.append(
                                "*Dollar bounty unavailable in HH export; using "
                                "estimated bounty model.*")
                    if _req_b is not None:
                        # Discount was applied -> Hero covers + safe (the producer
                        # zeroes the discount otherwise). Show the chip-only call
                        # threshold next to the PKO-adjusted one so the discount
                        # is explicit.
                        _po_lines.append(
                            f"**Chip-only call needs "
                            f"{_po.get('required_eq_pct', '\u2014')}%; "
                            f"PKO-adjusted call needs ~{_req_b:.1f}%** "
                            f"(\u2212{_bnt.get('discount_pp', 0):.1f}pp; "
                            "Hero covers \u2014 bounty collectible)")
                        _ev_b = _po.get('ev_call_bounty_bb')
                        if _ev_b is not None:
                            _po_lines.append(
                                f"**Bounty-adjusted EV:** {_ev_b:+.1f}BB")
                    elif _caveat:
                        # Mystery / multiway: value or collectibility unresolved.
                        _po_lines.append(
                            "**PKO adjustment unavailable / unsafe \u2014 review "
                            f"manually:** {_caveat}")
                    elif _covers is False:
                        # Cover status known: Hero does NOT cover -> the bounty is
                        # genuinely not collectible. A real conclusion, not a
                        # fabrication.
                        _po_lines.append(
                            "**Bounty:** no discount \u2014 Hero does not cover the "
                            "relevant villain, so the bounty is not collectible.")
                    else:
                        # Covers but modelled discount rounds to ~0, or
                        # collectibility otherwise unresolved -> no verdict.
                        _po_lines.append(
                            "**PKO adjustment unavailable \u2014 review manually:** "
                            "modelled discount is ~0 at this depth / "
                            "collectibility unresolved (not a high-confidence "
                            "PKO verdict).")
            # v8.14.1 rev-3 (Blocker 1): reconciled Bounty-trust strip \u2014 fires for
            # ANY bounty hand from the canonical cover fact, even when the detailed
            # bounty block above did not (no _po['bounty'] / no modelled threshold,
            # which is the common case for the flagged push/call-jam all-ins).
            # v8.14.1 consistency-fix (Blocker 2): when a BB-defense pko_context is
            # enabled, the PKO pill below renders its OWN, more specific Bounty-trust
            # strip \u2014 suppress this generic pot-odds strip so the hand never shows
            # two Bounty-trust lines for the same decision (prefer the specific one).
            _pko_will_strip = bool(((rd.get('pko_research') or {}).get('by_hand', {})
                                    .get(hid) or h.get('pko_context') or {}).get('enabled'))
            _bts = '' if _pko_will_strip else _bounty_trust_strip_md(rd, h, _po)
            if _bts:
                _po_lines.append(_bts)
            _ev = _po.get('ev_call_bb')
            _vh = _po.get('verdict_hint', '')
            if _ev is not None:
                _po_lines.append(f"**EV of call:** {_ev:+.1f}BB \u2014 _{_vh}_")
            # v8.16.4 DTI: OPTIONAL root/downstream attribution render support on
            # the XIV.A full card too. Renders ONLY when a producer stamped
            # h['attribution_roles'] = {street: role}; absent -> unchanged.
            try:
                from gem_review_trust import attribution_render_line as _arl_a
                _attr_a = _arl_a(h.get('attribution_roles') or {})
                if _attr_a:
                    _po_lines.append(_attr_a)
            except Exception:
                pass
            if _po_lines:
                _po_st = _street_attr(_po.get('street'))
                _po_ds = f" data-street='{_po_st}'" if _po_st else ''
                doc.w(f"<div class='analyst-notes'{_po_ds}>")
                doc.w("\U0001F4CA **Pot-Odds & Equity:**")
                doc.w("")
                for _pl in _po_lines:
                    doc.w(f"  {_pl}")
                doc.w("")
                doc.w("</div>")
                doc.w("")

        # v8.12.0: PKO research pill + coverage chip (renderer displays the
        # upstream pko_context fact only; Review language \u2014 never a mistake
        # claim). Routed under PRE-FLOP via data-street.
        # v8.12.1 P2: review-tier flag notes (cautious copy; no verdicts)
        for _rvf_f in (rd.get('review_flags') or {}).get(hid, []):
            _rvf_st = _street_attr(_rvf_f.get('street'))
            _rvf_ds = f" data-street='{_rvf_st}'" if _rvf_st else ''
            doc.w(f"<div class='analyst-notes'{_rvf_ds}>")
            doc.w(f"\U0001F9ED **Review:** {_rvf_f.get('copy', '')}")
            doc.w("</div>")
            doc.w("")

        _osz_note = _oversize_open_note(h)
        if _osz_note:
            doc.w("<div class='analyst-notes' data-street='preflop'>")
            doc.w(_osz_note)
            doc.w("</div>")
            doc.w("")

        _pko_ctx = ((rd.get('pko_research') or {}).get('by_hand', {})
                    .get(hid) or h.get('pko_context') or {})
        if _pko_ctx.get('enabled'):
            _pk_rng = _pko_ctx.get('delta_range_pp') or [0, 0]
            _pk_d = (f"{_pk_rng[0]:+.1f} to {_pk_rng[1]:+.1f}pp"
                     if _pk_rng[0] != _pk_rng[1] else f"{_pk_rng[0]:+.1f}pp")
            _pk_players = {2: 'HU', 3: '3-way', 4: '4-way'}.get(
                _pko_ctx.get('players_if_hero_continues'), '?')
            # v8.14.0 Slice E rev-2: re-reconcile the stamped cover facts WITH
            # the per-hand pot-odds facts (chip-only vs PKO-adjusted threshold,
            # discount, $ bounty) so the on-page strip proves the FULL math, and
            # downgrade a confident PKO classification on a trust contradiction.
            from gem_pko_research import pko_trust_render as _pko_trust_render
            _po_d = _po or {}
            _po_bnt = _po_d.get('bounty') or {}
            _pk_render = _pko_trust_render(
                _pko_ctx,
                bounty_usd=_pko_bounty_usd(rd, h),
                discount_pp=_po_bnt.get('discount_pp', 0) or 0,
                chip_threshold_pct=_po_d.get('required_eq_pct'),
                pko_threshold_pct=_po_d.get('required_eq_bounty_pct'),
                overjam_bb=None)
            _pk_cls = _pk_render['classification_display']
            # v8.12.8: exact-stack coverage label from the context builder
            # (collectibility from real stacks); legacy map only as fallback
            _cov_lbl = _pko_ctx.get('coverage_label') or {
                'Hero covers': 'covers opener',
                'Hero covered': 'covered by opener',
                'Equal': 'roughly equal stacks',
                'Mixed': 'mixed coverage'}.get(
                _pko_ctx.get('coverage_bucket', ''), '')
            doc.w("<div class='analyst-notes' data-street='preflop'>")
            doc.w(f"\U0001F3AF **PKO {_pk_cls}** \u00b7 "
                  f"{_pko_ctx.get('spot', '')} \u00b7 "
                  f"{_pko_ctx.get('depth_bucket', '')} "
                  f"(eff {_pko_ctx.get('effective_stack_bb', '?')}bb) "
                  f"\u00b7 {_pk_players} "
                  f"\u00b7 \u0394 {_pk_d} aggregate"
                  + (f" \u00b7 {_cov_lbl}"
                     if _cov_lbl else ""))
            # Slice E rev-2: compact reconciled "Bounty trust:" strip (cover /
            # collectibility / bounty $ / chip-vs-PKO threshold), with a visible
            # contradiction flag so a bounty conclusion can never fight its math.
            if _pk_render.get('strip_md'):
                doc.w("")
                doc.w("  " + _pk_render['strip_md'])
            # v8.17 Epic B (B7): the explicit "how the bounty changes the decision"
            # coaching line — built by pko_trust_render from the SAME reconciled
            # facts (no recompute). Empty on a contradiction / no-bounty / Hero-covered.
            if _pk_render.get('how_changes_md'):
                doc.w("")
                doc.w("  " + _pk_render['how_changes_md'])
            # v8.16.4 Obj 9 / v8.17 B6: user-visible bounty PROVENANCE — one of the
            # four honest states {exact / estimated current / flat event-start /
            # unavailable}, derived from the bounty $ + the model method, so a static
            # event-start figure is never shown as a per-decision dynamic value.
            # Reuses the same bounty fields the strip used (one source, no recompute).
            try:
                from gem_review_trust import bounty_provenance_label as _bpl
                _bp_usd = _pko_bounty_usd(rd, h)
                _bp_bb = _po_bnt.get('value_bb') or h.get('bounty_value_bb')
                _bp_method = str(_po_bnt.get('method') or '').lower()
                if _bp_usd is not None:
                    _bp_line = _bpl('exact', value_usd=_bp_usd, value_bb=_bp_bb)
                elif _bp_bb and ('ratio' in _bp_method or 'effective' in _bp_method
                                 or 'current' in _bp_method):
                    _bp_line = _bpl('effective_bb', value_bb=round(_bp_bb, 1))
                elif _bp_bb:
                    _bp_line = _bpl('starting_bb_flat', value_bb=round(_bp_bb, 1))
                else:
                    _bp_line = 'Bounty value unavailable'
                doc.w("")
                doc.w("  *" + _bp_line + "*")
            except Exception:
                pass
            doc.w("")
            doc.w(f"  {_pko_ctx.get('teaching_note', '')} "
                  f"*{_pko_ctx.get('caveat', '')}*")
            doc.w("")
            doc.w("</div>")
            doc.w("")

        # v8.14.1 rev-4 (Blocker D): a BOUNTY all-in whose collectibility can't be
        # resolved (no reliable jammer stack) gets neither a pot-odds Bounty-trust
        # strip (no _po) nor a PKO pill (not a BB-defense pko_context) \u2014 so the
        # bounty math was silently absent (73559949). Render an explicit note so
        # the user knows WHY rather than leaving it silent. Never fabricates math.
        if (not _po and not _pko_ctx.get('enabled')
                and h.get('format') == 'BOUNTY' and h.get('pf_allin')
                and h.get('bounty_collectible') in (None, 'unknown')):
            doc.w("<div class='analyst-notes' data-street='preflop'>")
            doc.w("\U0001f3af **PKO bounty math:** cover/collectibility unresolved "
                  "from the HH export, so this verdict uses chip-chart logic only. "
                  "Review manually.")
            doc.w("</div>")
            doc.w("")

        # v8.16.3 Range Lens v1: source-safe per-street range/commentary lines,
        # appended AFTER all existing commentary (preserves it; V25 routes by
        # data-street into each street card).
        _emit_range_lens(doc, h, hid_short)

        # B168 (Ron 2026-05-24): inline audit review row after the hand.
        # Bug C fix: use hero hole cards, not the last street's board cards
        _hole_title = _combo_to_chart(h.get('cards', []))
        doc.w(f"<<REVIEWROW|hand|{hid}|Hand {hid_short} \u2014 {_hole_title}>>")
        doc.w("</article>")
        doc.w("---")
        doc.w("")

    # B165: close the XIV.A collapsible (opened only when hand_ids_full).
    if hand_ids_full:
        doc.w("</details>")
        doc.w("")

    # ============ XIV.B — Compact Lookup Stubs ============
    # For every other hand_id referenced in the body (busts, deviations,
    # clinical examples, etc.) emit a compact stub so EVERY citation
    # link goes somewhere useful. No analyst notes — just heading +
    # context + Table at hand start + colored preflop action.
    if hand_ids_stub:
        # B86 (v7.57, Ron 2026-05-18): XIV.B redesign.
        # Previous: 263 hand stubs in a flat list with no analyst notes —
        # unclear what they were for.
        # New: group hand stubs by their citing section. Each section gets a
        # collapsible <details> block containing those hands rendered with
        # the SAME visual grid format used in XIV.A. Hands not cited anywhere
        # are excluded entirely (they have no purpose in the report).
        from collections import defaultdict

        # Build map of hand_id → list of (anchor, label) citations
        cite_groups = defaultdict(list)
        uncited = []
        for hid in hand_ids_stub:
            h = hands_by_id.get(hid)
            if not h:
                continue
            citations = _state._get_citations_for(hid)
            if citations:
                # Group under the FIRST citing section (each hand goes in one
                # bucket — collapse to most-relevant cite). Use the anchor as
                # key, label as display name.
                first_anchor, first_label = citations[0]
                cite_groups[(first_anchor, first_label)].append(hid)
            else:
                uncited.append(hid)

        # v8.4.5: Option B — group uncited-but-harvested hands under a catch-all
        # bucket instead of excluding them. These are hands referenced by data-hids
        # popup triggers but never cited via _register_citation.
        if uncited:
            cite_groups[('sec-metric-popups', 'Metric Popup References')] = uncited

        # Stats
        n_grouped = sum(len(v) for v in cite_groups.values())
        n_sections = len(cite_groups)

        doc.w("")
        doc.w("<<ANCHOR:sec-xivb-quick-lookups>>")
        doc.w(f"### XIV.B Quick Lookups ({n_grouped} hands across {n_sections} section(s))")
        doc.w("")
        doc.w(f"*{n_grouped} hand(s) grouped by their citing section. "
              f"Same visual format as XIV.A.*")
        doc.w("")

        # B165: Pick-candidate reasons keyed by hand id (for the why-here line)
        _bestplay_by_id = {}
        for _bc in (rd.get('bestplay_screen', []) or []):
            if isinstance(_bc, dict) and _bc.get('id'):
                _rs = (_bc.get('bestplay_screen', {}) or {}).get('reasons', [])
                if _rs:
                    _bestplay_by_id[_bc['id']] = _rs

        # Sort cite groups by section anchor (preserves report order roughly)
        sorted_groups = sorted(cite_groups.items(), key=lambda kv: kv[0][0])

        for (anchor, label), hids in sorted_groups:
            short_label = (label.split(' — ')[0] if label else anchor)[:60].rstrip()
            # B163 (Ron 2026-05-24): category emoji on the collapsed cite-group
            # so XIII-derived hand examples are identifiable while collapsed —
            # 🎈 Wide opens, 💤 Missed opens, ⚠️ Mistakes, 🦅 MDA exploits.
            _a, _l = (anchor or '').lower(), (label or '').lower()
            if 'xiii-1' in _a or 'wide open' in _l:
                _cat_emoji = '🎈 '
            elif 'xiii-3' in _a or 'missed open' in _l or 'missed steal' in _l:
                _cat_emoji = '💤 '
            elif 'xiii-5' in _a or 'mda' in _l or 'exploit' in _l or 'top-leaks' in _a:
                _cat_emoji = '🦅 '
            elif 'xiii-4-tail' in _a or 'tail fold' in _l:
                _cat_emoji = '⚪ '
            elif 'xiii-4' in _a or 'mistake' in _l:
                _cat_emoji = '⚠️ '
            elif 'iii-8' in _a or 'pick' in _l:
                _cat_emoji = '⭐ '
            else:
                _cat_emoji = ''
            # Only prefix with xivb- if anchor collides with a main section heading
            # (pattern: sec-N-N). sec-metric-popups is unique — keep as-is.
            import re as _re_anc
            _xivb_anchor = f"xivb-{anchor}" if _re_anc.match(r'^sec-\d', anchor) else anchor
            doc.w(f"<<ANCHOR:{_xivb_anchor}>>")
            doc.w(f"<details id='xivb-from-{anchor}'>")
            # v8.6.2: XIV.B appendix size cap. Default 20 per group,
            # Metric Popup References default 10. Env var overrides.
            # v8.12.4 (QA item 19): with lazy hands ON a stub costs ~0.6KB
            # compressed — the caps were the second layer (after the
            # appendix-ids cap) that left popup-cited hands with dead
            # clicks. Lazy builds render every cited stub; classic builds
            # keep the old caps.
            import os as _os_cap
            _lazy_on_xivb = _os_cap.environ.get('GEM_LAZY_HANDS', '1') == '1'
            _cap_default = '0' if _lazy_on_xivb else '100'
            try:
                _xivb_cap = int(_os_cap.environ.get('GEM_XIVB_CAP', _cap_default)
                                or _cap_default)
            except ValueError:
                _xivb_cap = 0 if _lazy_on_xivb else 20
            _is_popup_refs = anchor == 'sec-metric-popups'
            if _is_popup_refs:
                _pop_default = '0' if _lazy_on_xivb else '10'
                try:
                    _xivb_cap = int(_os_cap.environ.get('GEM_XIVB_POPUP_CAP',
                                                        _pop_default) or _pop_default)
                except ValueError:
                    _xivb_cap = 0 if _lazy_on_xivb else 10
            _hids_full = list(hids)
            # HA3: P0/P1 hands always survive the group cap
            _prios = _state._APPENDIX_HAND_PRIORITIES
            _hids_priority = [h for h in _hids_full if _prios.get(h, 2) <= 1]
            _hids_regular = [h for h in _hids_full if _prios.get(h, 2) > 1]
            _hids_render = _hids_priority + _hids_regular[:max(0, _xivb_cap - len(_hids_priority))]
            if _xivb_cap <= 0:
                _hids_render = _hids_full
            _n_trimmed = len(_hids_full) - len(_hids_render)
            _cap_note = (f" — showing first {len(_hids_render)} of {len(_hids_full)}"
                         if _n_trimmed > 0 else '')
            doc.w(f"<summary><strong>{_cat_emoji}Cited from {short_label}</strong> "
                  f"({len(_hids_full)} hand(s){_cap_note}) — "
                  f"<a href='#{anchor}'>jump to section ↑</a></summary>")
            doc.w("")
            for hid in _hids_render:
                if not hid:
                    continue
                h = hands_by_id.get(hid)
                if not h:
                    continue
                hid_short = hid[-8:] if len(hid) > 8 else hid
                if not hid_short:
                    continue
                stack_bb = h.get('stack_bb') or 0
                net_bb = h.get('net_bb') or 0
                pos = h.get('position', '?')
                hero_cards_list = h.get('cards') or []
                cards_pills = _cards_html(hero_cards_list, sort_desc=True) if hero_cards_list else '—'
                # BB pill (B74-style)
                if net_bb > 0:
                    bb_html = f"<span class='hand-net-pos'>+{net_bb:.1f} BB</span>"
                elif net_bb < 0:
                    bb_html = f"<span class='hand-net-neg'>{net_bb:.1f} BB</span>"
                else:
                    bb_html = f"<span class='hand-net-neu'>0 BB</span>"
                tname = (h.get('tournament') or '')[:50].rstrip()
                # Phase 4.5: hand-detail-card wrapper
                app_details = rd.get('appendix_hand_details', {}).get(hid, {})
                # Handover 2026-06-11 §6.3: machine-readable context on every
                # appendix card so URL/format verification passes are fully
                # programmatic (format was unknowable for ~499/507 linked hands).
                _va_fmt = _html_escape(h.get('format', '') or '')
                _va_ph = _html_escape(h.get('tournament_phase', '') or '')
                _va_eff = h.get('eff_stack_bb') or h.get('stack_bb') or 0
                _va_t = _html_escape(str(h.get('tournament', '') or ''))
                _state._FULL_CARD_IDS.add(hid_short)  # v8.16.2 Phase B: full card -> never also a XIV.C stub
                doc.w(f"<article class='hand-detail-card' data-hand-id='{hid_short}' "
                      f"data-format='{_va_fmt}' data-phase='{_va_ph}' "
                      f"data-eff-bb='{_va_eff:.1f}' data-tournament='{_va_t}'>")
                # Phase 4.7 C3: mh-top / mh-title wrapper (v29 vocabulary)
                doc.w("<div class='mh-top'><div class='mh-title'>")
                doc.w(f"<<ANCHOR:sec-app-hand-{hid_short}>>")
                _agl = _agg_gate_label(hid, rd)
                _agl_str = f" · {_agl[0]} {_agl[1]}" if _agl else ''
                # B-path: _flag not bound yet here; the pill falls back to the
                # hand-level EAI facts (Suckout/Cooler/Flip) via empty verdict.
                _vp_b = __import__("gem_report_draft._helpers", fromlist=["short_verdict_pill"]).short_verdict_pill(h, "", app_details)
                doc.w(f"##### Hand `{hid_short}` — {cards_pills} ({pos} {stack_bb:.1f}BB) · {bb_html}{_agl_str}" + (f" {_vp_b}" if _vp_b else ""))
                doc.w("</div>")  # close mh-title
                doc.w("<div class='mh-actions'>")
                _emit_gtow_button(doc, h, app_details, hid_short, rd=rd)
                doc.w("</div>")
                doc.w("</div>")  # close mh-top
                doc.w("")
                # Compact meta line
                fmt = h.get('format', '—')
                lvl = h.get('level', '—')
                _phase_meta = (h.get('tournament_phase') or '').replace('_', ' ').strip()
                _phase_seg = f" · {_phase_meta.title()}" if _phase_meta else ''
                doc.w(f"*{tname} · {h.get('date','—')} · {fmt} · L{lvl}{_phase_seg}*")
                doc.w("")
                # B128 (Ron 2026-05-20): flagged XIV.B hands follow the SAME
                # structure as XIV.A — a *Flagged:* line (verdict-style) with a
                # *Mentioned in:* back-link, and the why-flagged comment in the
                # numbered yellow analyst-notes block with a (N) pill on the
                # Hero action it refers to. Reuses _split_argument_into_notes
                # + _render_hand_grid_table exactly as XIV.A does.
                _flag = _xivb_flag_note(hid, s, rd, h)
                # v8.8.6 S1-fix: satellite caveat — inline into XIV.B coaching text
                _xivb_fmt = (h.get('format') or '').upper()
                _xivb_icm = h.get('icm_pressure', 0) or 0
                if _flag and (_xivb_fmt == 'SATELLITE' or _xivb_icm > 0.7):
                    _ex_b = _flag.get('explanation', '')
                    if _ex_b:
                        _flag['explanation'] = _ex_b.replace(
                            'folding it is the leak',
                            'folding it is the leak by chipEV — but satellite/ICM may make folding defensible'
                        ).replace(
                            'passing on it is the deviation',
                            'passing on it is the deviation by chipEV — satellite/ICM may override')
                _back = f"[{short_label} ↑](#{anchor})"
                # Minimal back-link above the grid; full explanation goes BELOW
                doc.w(f"<span class='ie-wc'>{_md_inline(_back)}</span>")
                doc.w("")
                # Store the "why here" content to emit AFTER the grid.
                # B227 (Ron 2026-06-01): when the flag explanation gets wired
                # into the grid's numbered notes (via _split_argument_into_notes)
                # it must NOT also appear as a loose block below — that causes
                # the duplicate-with-raw-HTML-tags bug.  We set _why_here_content
                # here, then suppress it at emit time if notes_b consumed it.
                _why_here_content = None
                _why_here_st = ''
                if _flag:
                    _why_here_content = f"{_flag['emoji']} {_flag['label']}"
                    if _flag.get('explanation'):
                        _why_here_content += f"\n\n{_flag['explanation']}"
                elif not _agg_candidates(hid, rd):
                    _bpc = _bestplay_by_id.get(hid)
                    if _bpc:
                        _why_here_content = ("⭐ Pokerbot's Pick candidate — "
                                             f"screened on: {'; '.join(_bpc)}.")
                    else:
                        _why_here_content, _why_here_st = _why_here_text(anchor, short_label)
                        # Q5: enrich all-in hands with range commentary
                        _q5_rng_b = _allin_range_note(h)
                        if _q5_rng_b:
                            _why_here_content = (_why_here_content or '') + _q5_rng_b
                        if not _why_here_st and 'viii-4' in (anchor or '').lower():
                            _cr_b = h.get('check_raises', [])
                            if _cr_b:
                                _why_here_st = _street_attr(_cr_b[0])
                # B225 (Ron review 2026-05-25): if IV.6 confirmed this hand as
                # missed river value, surface the solver EV detail here with a
                # B235 (Ron review 2026-05-25): the solver note was a loose
                # line here, above the grid. It now lands in the yellow
                # analyst-notes block under the grid via _emit_agg_gate_block.
                # Visual hand grid (reuses XIV.A renderer)
                # (app_details already defined above for GTOW button)
                board = h.get('board') or []
                all_actions_b = app_details.get('actions') or {}
                pot_by_street_b = _compute_pot_by_street(all_actions_b, h)
                used_streets_b = []
                for street in ('preflop', 'flop', 'turn', 'river'):
                    st_actions_list = all_actions_b.get(street) or []
                    cards = _street_cards(board, street)
                    if st_actions_list or cards:
                        used_streets_b.append(street)
                # Build numbered notes so the grid shows 👍 on clean actions
                # and (N) on the flagged one.
                notes_b, a2n_b, a2t_b, snn_b = [], {}, {}, None
                hero_acts_b = _hero_actions_by_street_from_app(app_details)
                _hero_verbs_b = _hero_action_verbs_by_street_from_app(app_details)
                if _flag and _flag.get('explanation'):
                    notes_b, a2n_b, a2t_b, snn_b = _split_argument_into_notes(
                        _flag['explanation'], '', '', '', '',
                        hero_acts_b, analyst_street=_flag.get('street'),
                        hero_action_verbs_by_street=_hero_verbs_b)
                elif not _flag:
                    # Wire aggression gate commentary through the notes system
                    # so hero actions get 👍 (clean) and (N) (flagged).
                    _agg_cands_notes = _agg_candidates(hid, rd)
                    if _agg_cands_notes:
                        # Build a combined commentary from all aggression candidates
                        _agg_parts = []
                        _agg_street = None
                        for _ac_n in _agg_cands_notes:
                            _ae_n, _al_n = _agg_one_label(_ac_n)
                            _ac_st = _ac_n.get('street_of_interest', '')
                            if not _agg_street:
                                _agg_street = _ac_st
                            _agg_parts.append(
                                f"{_ac_st.capitalize()}: {_ae_n} {_al_n}. "
                                f"{_agg_commentary(_ac_n)}")
                        _agg_text = ' '.join(_agg_parts)
                        notes_b, a2n_b, a2t_b, snn_b = _split_argument_into_notes(
                            _agg_text, '', '', '', '',
                            hero_acts_b, analyst_street=_agg_street,
                            hero_action_verbs_by_street=_hero_verbs_b)
                _vsn_emitted_b = False  # v8.12.8 QA2: per-hand reset
                if used_streets_b and any((all_actions_b.get(s) or []) for s in used_streets_b):
                    # Hero hand display
                    if hero_cards_list:
                        pos_suffix = f" <span class='hero-pos'>in the {pos}</span>" if pos != '?' else ''
                        _nick = nickname_for(hero_cards_list)
                        nick_html = f" <span class='hero-nick'>{_nick}</span>" if _nick else ''
                        _phase_b = (h.get('tournament_phase') or '').replace('_', ' ').strip()
                        _phase_html_b = (f" <span class='hero-phase'>· {_phase_b.title()}</span>"
                                         if _phase_b else '')
                        doc.w(f"<div class='hero-hand'><span class='label'>Hero:</span> "
                              f"<span class='cards'>{cards_pills}</span>{pos_suffix}{nick_html}{_phase_html_b}</div>")
                        doc.w("")
                    _vb_b = _build_villain_badges(hid, s)   # full hid — atoms_by_hand keyed by full form
                    _render_hand_grid_table(doc, h, app_details, board, notes_b,
                                             a2n_b, pot_by_street_b, used_streets_b,
                                             rd=rd, action_to_tone=a2t_b,
                                             single_narrative_note_num=snn_b,
                                             villain_badges=_vb_b)
                    # v8.12.8 QA2: stubs carry villain badges, so they must
                    # carry the paired ❗ Note block too (was XIV.A-only).
                    _vsn_emitted_b = _emit_villain_street_notes(
                        doc, s, hid, hid_short)
                elif _flag and _flag.get('explanation'):
                    # No grid actions to pin a pill to — still show the note.
                    _ds_attr2 = _street_attr(_flag.get('street'))
                    _ds_tag2 = f" data-street='{_ds_attr2}'" if _ds_attr2 else ''
                    doc.w(f"<div class='analyst-notes'{_ds_tag2}>")
                    doc.w(f"⚠️ **Why flagged:** {_flag['explanation']}")
                    doc.w("</div>")
                else:
                    # v8.12.9 (GPT QA P1.6): 40 metric-only stubs opened to
                    # near-empty cards — say WHY there is no replay instead
                    # of looking broken.
                    doc.w("<div class='analyst-notes no-replay-reason'>")
                    doc.w("ℹ️ **No action replay for this hand.** It is "
                          "referenced by a metric or popup count, but its "
                          "street-by-street actions were not selected for "
                          "replay (no flagged decision). The hand ID and "
                          "result above are still exact.")
                    doc.w("</div>")
                doc.w("")
                # B201 (Ron 2026-05-25): a single aggression review is now
                # pinned into the grid (returned as _flag, street-numbered) —
                # don't also render it as a block below. The block now only
                # carries the multi-street case (2+ candidates).
                _has_notes_b = bool(_flag) or _vsn_emitted_b
                # Emit the "why here" content BELOW the grid in yellow notes.
                # B227: suppress when notes_b already consumed the flag's
                # explanation into the grid (avoids duplicate + HTML leak).
                if _why_here_content and not (_flag and notes_b):
                    _ds_attr3 = _street_attr(_flag.get('street')) if _flag else _street_attr(_why_here_st)
                    _ds_tag3 = f" data-street='{_ds_attr3}'" if _ds_attr3 else ''
                    doc.w(f"<div class='analyst-notes'{_ds_tag3}>")
                    doc.w(_why_here_content)
                    doc.w("</div>")
                    doc.w("")
                    _has_notes_b = True
                if not (_flag and _flag.get('_agg')):
                    _agg_cands_b = _agg_candidates(hid, rd)
                    if _agg_cands_b:
                        _emit_agg_gate_block(doc, hid, rd, hand=h)
                        _has_notes_b = True
                else:
                    _scn_b = _solver_confirm_note(hid, rd)
                    if _scn_b:
                        doc.w("<div class='analyst-notes' data-street='river'>")
                        doc.w(_scn_b)
                        doc.w("</div>")
                        doc.w("")
                    _has_notes_b = True

                # v8.17.1 P1 (§9 capsule de-gate, compact/lazy path): the
                # register-classified DECISION capsule LEAD is built for EVERY
                # scored/evidenced hand on the compact path too (C2 parity) — not
                # only hands with a pot-odds object. _po_b is ONE optional Math
                # anchor. Emits only with a visible anchor OR a gradable decision;
                # the detailed notes (range block, _po_b lines, villain notes) all
                # render BELOW this lead (zero-drop).
                if h:
                    try:
                        from gem_commentary_capsule import (
                            decision_capsule_from_signals as _dcs_b,
                            render_capsule_md as _rcm_b)
                        from gem_review_trust import (
                            classify_preflop_allin as _cpa_bl,
                            allin_kind_label as _akl_bl,
                            multiway_render_plan as _mwp_bl)
                        from gem_report_draft._helpers import hand_range_evidence as _hre_bl
                        _po_bl = ((rd.get('pot_odds_by_hand') or {}).get(hid)
                                  or (rd.get('pot_odds_by_hand') or {}).get(hid_short) or {})
                        _rev_bl = _hre_bl(h) or {}
                        _capdec_bl = ''
                        if h.get('pf_allin'):
                            _kc_bl = _cpa_bl(h)[0]
                            if _kc_bl != 'not_allin':
                                _capdec_bl = _akl_bl(_kc_bl)
                        _rng_bl = ''
                        if (_rev_bl.get('hero_hand')
                                and _rev_bl.get('membership') in ('inside', 'outside')):
                            _ck_bl = (_rev_bl.get('chart_key')
                                      or _rev_bl.get('spot_label') or 'range')
                            _rng_bl = '%s %s %s' % (
                                _rev_bl['hero_hand'],
                                'inside' if _rev_bl['membership'] == 'inside' else 'outside',
                                _ck_bl)
                        _mwp_bp = {'suppress_hu_required_equity': False}
                        if _po_bl:
                            try:
                                _mwp_bp = _mwp_bl(
                                    n_live_opponents=max(0, (_po_bl.get('n_players_at_showdown') or 0) - 1),
                                    players_still_to_act=_po_bl.get('players_still_to_act', 0) or 0)
                            except Exception:
                                pass
                        _why_bl = ((rd.get('analyst_commentary') or {}).get(hid, {})
                                   or {}).get('hand_strength', '')
                        _cap_bl = _dcs_b(
                            (_po_bl.get('street') if _po_bl else None)
                                or (h.get('hero_decision_street') or '').lower() or 'preflop',
                            decision_label=_capdec_bl,
                            verdict_hint=_po_bl.get('verdict_hint', '') if _po_bl else '',
                            analyst_why=_why_bl,
                            required_eq_pct=_po_bl.get('required_eq_pct') if _po_bl else None,
                            multiway_suppressed=bool(_mwp_bp.get('suppress_hu_required_equity')),
                            range_line=_rng_bl)
                        if _cap_bl and (_cap_bl.get('has_anchor') or _capdec_bl):
                            _cs_bl = _street_attr(_cap_bl.get('street'))
                            _ds_bl = f" data-street='{_cs_bl}'" if _cs_bl else ''
                            doc.w(f"<div class='analyst-notes pb-capsule pb-cap-{_cap_bl['register']}'{_ds_bl}>")
                            doc.w(_rcm_b(_cap_bl))
                            doc.w("</div>")
                            doc.w("")
                            _has_notes_b = True
                            h['_pb_capsule_emitted'] = True
                    except Exception:
                        pass

                # v8.14.1 P0-2: chart-backed Range evidence block on XIV.B stubs
                # too (same shared builder as XIV.A) so referenced preflop range
                # decisions also carry visible evidence.
                if h:
                    try:
                        from gem_report_draft._helpers import (
                            hand_range_evidence as _hre_b,
                            range_evidence_md as _rem_b)
                        _rev_b = _hre_b(h)
                        if _rev_b:
                            doc.w("")
                            doc.w(_rem_b(_rev_b))
                    except Exception:
                        pass

                # Pot odds rendering for XIV.B (same as XIV.A BUG-12 fix)
                _po_b = (rd.get('pot_odds_by_hand') or {}).get(hid) or \
                         (rd.get('pot_odds_by_hand') or {}).get(hid_short)
                if _po_b:
                    _po_lines_b = []
                    _po_lines_b.append(f"**Pot odds:** {_po_b.get('pot_odds', '—')} "
                                       f"(call {_po_b.get('call_bb', '—')}BB)")
                    # v8.16.4 DTI Blocker 2: the COMPACT path (the one most hands
                    # actually open) now carries the SAME decision evidence as the
                    # full card — consuming the SAME _po_b object, no recompute:
                    # a structurally-provable all-in DECISION-KIND label, and the
                    # multiway suppression of the heads-up required-equity line.
                    try:
                        from gem_review_trust import (
                            multiway_render_plan as _mwp_b,
                            classify_preflop_allin as _cpa_b, allin_kind_label as _akl_b)
                        _mw_b = _mwp_b(
                            n_live_opponents=max(0, (_po_b.get('n_players_at_showdown') or 0) - 1),
                            players_still_to_act=_po_b.get('players_still_to_act', 0) or 0)
                        if h.get('pf_allin'):
                            _k_b = _cpa_b(h)[0]
                            if _k_b != 'not_allin':
                                _po_lines_b.append("**Decision:** " + _akl_b(_k_b))
                    except Exception:
                        _mw_b = {'suppress_hu_required_equity': False,
                                 'pot_odds_uncertain': False, 'label': ''}
                    _req_b = _po_b.get('required_eq_pct')
                    _mw_sup_b = bool(_mw_b.get('suppress_hu_required_equity'))
                    # v8.17.1 P1: the §9 decision-capsule LEAD now renders ABOVE
                    # (de-gated from `if _po_b:` so it covers every scored/evidenced
                    # compact-path hand). Here _po_b only emits the detailed lines.
                    if _req_b and not _mw_sup_b:
                        _po_lines_b.append(f"**Required equity:** {_req_b}%")
                    elif _mw_sup_b:
                        _po_lines_b.append(
                            (_mw_b.get('label') or 'Multiway all-in')
                            + " — compare your equity to the FIELD, not one villain"
                            + ("; players still to act (pot odds uncertain)"
                               if _mw_b.get('pot_odds_uncertain') else ""))
                    _eq_b = _po_b.get('hero_equity_pct')
                    if _eq_b is not None:
                        _po_lines_b.append(f"**Hero equity vs range:** {_eq_b:.1f}%")
                    _vh_b = _po_b.get('verdict_hint', '')
                    if _vh_b:
                        _po_lines_b.append(f"**Verdict:** _{_vh_b}_")
                    if _po_lines_b:
                        _po_st_b = _street_attr(_po_b.get('street'))
                        _po_ds_b = f" data-street='{_po_st_b}'" if _po_st_b else ''
                        doc.w(f"<div class='analyst-notes'{_po_ds_b}>")
                        doc.w("📊 " + " · ".join(_po_lines_b))
                        # v8.14.1 rev-3 (Blocker 5): attach the required-equity
                        # teaching line to EVERY visible Required-equity line, not
                        # only the comprehensive XIV.A block. This is the compact
                        # XIV.B path that 73281169 / 72696769 actually render on.
                        if _req_b and not _mw_sup_b:
                            doc.w("")
                            doc.w("*This is the share you need to win versus the "
                                  "betting/jamming range (including draws and worse "
                                  "hands) to break even — not how often you are "
                                  "ahead right now.*")
                        # v8.14.1 rev-3 (Blocker 1): reconciled Bounty-trust strip on
                        # the compact XIV.B path too (push/call-jam all-ins land here).
                        # v8.14.1 consistency-fix (Blocker 2): suppress this generic
                        # strip when the XIV.B PKO pill below will render its own more
                        # specific Bounty-trust strip (BB-defense pko_context enabled),
                        # so 72696769 / 73281169 show exactly one Bounty-trust line.
                        _pko_will_strip_b = bool(((rd.get('pko_research') or {})
                                                  .get('by_hand', {}).get(hid)
                                                  or h.get('pko_context') or {}).get('enabled'))
                        _bts_b = '' if _pko_will_strip_b else _bounty_trust_strip_md(rd, h, _po_b)
                        if _bts_b:
                            doc.w("")
                            doc.w(_bts_b)
                        # v8.16.4 DTI Blocker 2/Obj 9: bounty provenance on the
                        # compact path (exact $ vs flat starting-BB estimate),
                        # reusing the same bounty fields (one source, no recompute).
                        try:
                            from gem_review_trust import bounty_provenance_label as _bpl_b
                            _bb_b = ((_po_b.get('bounty') or {}).get('value_bb')
                                     or h.get('bounty_value_bb'))
                            _usd_b = _pko_bounty_usd(rd, h)
                            if _usd_b is not None:
                                doc.w("")
                                doc.w("*" + _bpl_b('exact', value_usd=_usd_b, value_bb=_bb_b) + "*")
                            elif _bb_b:
                                doc.w("")
                                doc.w("*" + _bpl_b('starting_bb_flat', value_bb=round(_bb_b, 1)) + "*")
                        except Exception:
                            pass
                        # v8.16.4 DTI: OPTIONAL root/downstream attribution render
                        # support. Renders ONLY when a producer has stamped
                        # h['attribution_roles'] = {street: role}; absent -> the
                        # hand is unchanged. Schema/render only (no re-grading).
                        try:
                            from gem_review_trust import attribution_render_line as _arl_b
                            _attr_b = _arl_b(h.get('attribution_roles') or {})
                            if _attr_b:
                                doc.w("")
                                doc.w("*" + _attr_b + "*")
                        except Exception:
                            pass
                        doc.w("</div>")
                        doc.w("")
                        _has_notes_b = True

                # v8.12.0: PKO pill + coverage chip — XIV.B parity with the
                # XIV.A path (same upstream fact, Review language only).
                # v8.12.1 P2: review-tier flag notes (XIV.B parity)
                for _rvf_fb in (rd.get('review_flags') or {}).get(hid, []):
                    _rvf_stb = _street_attr(_rvf_fb.get('street'))
                    _rvf_dsb = (f" data-street='{_rvf_stb}'"
                                if _rvf_stb else '')
                    doc.w(f"<div class='analyst-notes'{_rvf_dsb}>")
                    doc.w(f"🧭 **Review:** "
                          f"{_rvf_fb.get('copy', '')}")
                    doc.w("</div>")
                    doc.w("")

                _osz_b = _oversize_open_note(h)
                if _osz_b:
                    doc.w("<div class='analyst-notes' data-street='preflop'>")
                    doc.w(_osz_b)
                    doc.w("</div>")
                    doc.w("")
                    _has_notes_b = True

                _pko_ctx_b = ((rd.get('pko_research') or {}).get('by_hand', {})
                              .get(hid) or h.get('pko_context') or {})
                if _pko_ctx_b.get('enabled'):
                    _pkb_rng = _pko_ctx_b.get('delta_range_pp') or [0, 0]
                    _pkb_d = (f"{_pkb_rng[0]:+.1f} to {_pkb_rng[1]:+.1f}pp"
                              if _pkb_rng[0] != _pkb_rng[1]
                              else f"{_pkb_rng[0]:+.1f}pp")
                    _pkb_pl = {2: 'HU', 3: '3-way', 4: '4-way'}.get(
                        _pko_ctx_b.get('players_if_hero_continues'), '?')
                    _pkb_cov = _pko_ctx_b.get('coverage_label') or {
                        'Hero covers': 'covers opener',
                        'Hero covered': 'covered by opener',
                        'Equal': 'roughly equal stacks',
                        'Mixed': 'mixed coverage'}.get(
                        _pko_ctx_b.get('coverage_bucket', ''), '')
                    # v8.14.1 rev-4 (Blocker A): downgrade a confident PKO class on
                    # a multiway / unresolved-collectibility spot, exactly like the
                    # XIV.A pill — the XIV.B pill previously printed the RAW
                    # classification, so "PKO Good/Too wide/Missed" still leaked on
                    # 3-way / open+caller uncertainty spots.
                    from gem_pko_research import pko_trust_render as _pko_trust_render_b
                    _po_db = _po_b or {}
                    _po_bnt_b = _po_db.get('bounty') or {}
                    # v8.17 C2 parity: the XIV.B compact pill now carries the SAME
                    # reconciled trust strip + "how the bounty changes the decision"
                    # coaching + 4-state provenance as the XIV.A full card (same
                    # _po_b object, no recompute) — not just the downgraded class.
                    _pkb_render = _pko_trust_render_b(
                        _pko_ctx_b,
                        bounty_usd=_pko_bounty_usd(rd, h),
                        discount_pp=_po_bnt_b.get('discount_pp', 0) or 0,
                        chip_threshold_pct=_po_db.get('required_eq_pct'),
                        pko_threshold_pct=_po_db.get('required_eq_bounty_pct'),
                        overjam_bb=None)
                    _pkb_cls = _pkb_render['classification_display']
                    doc.w("<div class='analyst-notes' data-street='preflop'>")
                    doc.w(f"🎯 **PKO "
                          f"{_pkb_cls}** · "
                          f"{_pko_ctx_b.get('spot', '')} · "
                          f"{_pko_ctx_b.get('depth_bucket', '')} "
                          f"(eff {_pko_ctx_b.get('effective_stack_bb', '?')}bb) "
                          f"· {_pkb_pl} "
                          f"· Δ {_pkb_d} aggregate"
                          + (f" · {_pkb_cov}"
                             if _pkb_cov else ""))
                    if _pkb_render.get('strip_md'):
                        doc.w("")
                        doc.w("  " + _pkb_render['strip_md'])
                    if _pkb_render.get('how_changes_md'):
                        doc.w("")
                        doc.w("  " + _pkb_render['how_changes_md'])
                    try:
                        from gem_review_trust import bounty_provenance_label as _bpl_pb
                        _pb_usd = _pko_bounty_usd(rd, h)
                        _pb_bb = _po_bnt_b.get('value_bb') or h.get('bounty_value_bb')
                        _pb_method = str(_po_bnt_b.get('method') or '').lower()
                        if _pb_usd is not None:
                            _pb_line = _bpl_pb('exact', value_usd=_pb_usd, value_bb=_pb_bb)
                        elif _pb_bb and ('ratio' in _pb_method or 'effective' in _pb_method
                                         or 'current' in _pb_method):
                            _pb_line = _bpl_pb('effective_bb', value_bb=round(_pb_bb, 1))
                        elif _pb_bb:
                            _pb_line = _bpl_pb('starting_bb_flat', value_bb=round(_pb_bb, 1))
                        else:
                            _pb_line = 'Bounty value unavailable'
                        doc.w("")
                        doc.w("  *" + _pb_line + "*")
                    except Exception:
                        pass
                    doc.w("")
                    doc.w(f"  {_pko_ctx_b.get('teaching_note', '')} "
                          f"*{_pko_ctx_b.get('caveat', '')}*")
                    doc.w("")
                    doc.w("</div>")
                    doc.w("")
                    _has_notes_b = True

                # v8.7.0 PR2: Compact facing strip — one-line villain context
                _vi_fs = h.get('villain_identity', {}) or {}
                _vi_alias = _vi_fs.get('alias', '')
                _vi_code = _vi_fs.get('code', '')
                _vi_arch_label = h.get('villain_archetype_label', '')
                _vi_conf = _vi_fs.get('confidence', '')
                _vi_n = _vi_fs.get('n_hands', 0)
                _vi_vk = _vi_fs.get('villain_key', '') or h.get('primary_villain_key', '')
                _vi_exploits = h.get('exploit_opportunities', []) or []
                if _vi_alias and _vi_code and _vi_arch_label:
                    _fs_cls = 'facing-strip has-exploit' if _vi_exploits else 'facing-strip'
                    _emoji = _vi_arch_label.split(' ')[0] if _vi_arch_label else ''
                    _arch_name = _vi_arch_label.split(' ', 1)[1] if ' ' in _vi_arch_label else _vi_arch_label
                    _conf_str = _vi_conf.replace('_', '-') if _vi_conf else ''
                    _evidence_n = _vi_n
                    _fs_title = f'{_vi_alias} · {_vi_code}'
                    _fs_sub = f'{_arch_name} · {_conf_str} conf · {_evidence_n} hands'
                    # Evidence link button
                    _fs_action = ''
                    if _vi_vk:
                        _fs_action = (f'<span class="facing-action" '
                                      f'onclick="openVillainEvidence(\'{_html_escape(_vi_vk)}\')">'
                                      f'Evidence ({_evidence_n})</span>')
                    doc.w(f"<div class='{_fs_cls}'>")
                    doc.w(f"  <div class='facing-main'>")
                    doc.w(f"    <div class='facing-icon'>{_emoji}</div>")
                    doc.w(f"    <div class='facing-inline'>")
                    doc.w(f"      <span class='facing-title'>{_html_escape(_fs_title)}</span>")
                    doc.w(f"      <span class='facing-sep'>·</span>")
                    doc.w(f"      <span class='facing-sub'>{_html_escape(_fs_sub)}</span>")
                    doc.w(f"    </div>")
                    doc.w(f"  </div>")
                    if _fs_action:
                        doc.w(f"  <div class='facing-actions'>{_fs_action}</div>")
                    doc.w(f"</div>")

                # Villain archetype + misplay note with teaching context
                _v_arch = h.get('villain_archetype_label', '')
                _v_exploit = h.get('villain_exploit_note', '')
                _v_reason = h.get('villain_archetype_reason', '')
                _v_example_hids = h.get('villain_example_hids', [])
                _v_misplay = h.get('archetype_misplay')
                if _v_arch or _v_misplay:
                    _v_sample = h.get('villain_hand_count', '')
                    _v_sample_str = f' · {_v_sample}-hand sample' if _v_sample else ''
                    _v_label = _v_misplay.get('archetype_label', _v_arch) if _v_misplay else _v_arch
                    # v8.4.0: use villain identity (alias + V-code) if available
                    _vi = h.get('villain_identity', {})
                    if _vi.get('alias') and _vi.get('code'):
                        _v_display = f"{_vi['alias']} · {_vi['code']} · {_v_label}"
                        _v_conf = _vi.get('confidence', '')
                        _v_conf_str = f' · {_v_conf.replace("_", "-")} confidence' if _v_conf else ''
                        # v8.7.0: show villain_key in tooltip for debugging
                        _vk_raw = _vi.get('villain_key') or h.get('primary_villain_key', '')
                        if _vk_raw:
                            _v_display = (f'<span title="villain key: {_html_escape(_vk_raw)}">'
                                          f'{_v_display}</span>')
                    else:
                        _v_display = _v_label
                        _v_conf_str = _v_sample_str
                    doc.w("<div class='analyst-notes'>")
                    doc.w(f"<details><summary>🎭 <b>Villain:</b> {_v_display}{_v_conf_str}</summary>")
                    doc.w("")
                    if _v_misplay:
                        if _v_reason:
                            doc.w(f"  *Why this tag:* {_v_reason}")
                        doc.w(f"  **Misplay:** {_v_misplay.get('misplay_type', '')}")
                        doc.w(f"  **Correct play:** {_v_misplay.get('what_to_do', '')}")
                    elif _v_arch:
                        if _v_reason:
                            doc.w(f"  *Why this tag:* {_v_reason}")
                        if _v_exploit:
                            doc.w(f"  *Exploit:* {_v_exploit}")
                    # Link to example hands — use prior examples if available,
                    # otherwise collect ALL hands vs this villain from the session
                    _ve_ids = list(_v_example_hids or [])
                    if not _ve_ids:
                        # v8.7.0: use primary_villain_key (tournament_id|player_hash)
                        # to find ALL hands where this specific player appeared.
                        _pvk = h.get('primary_villain_key', '')
                        if _pvk:
                            _pv_tid, _, _pv_hash = _pvk.partition('|')
                            if _pv_hash:
                                _ve_ids = [_hh.get('id') for _hh in hands
                                           if (_hh.get('tournament_id') == _pv_tid
                                               and _pv_hash in (_hh.get('villains') or {})
                                               and _hh.get('id') and _hh.get('id') != hid
                                               and _hh.get('vpip'))][:10]
                        # Fallback: find hands by position (legacy approach)
                        if not _ve_ids:
                            _v_opener = h.get('opener_position', '')
                            _v_tourney = (h.get('tournament') or '')[:30]
                            if _v_opener and _v_tourney:
                                _ve_ids = [_hh.get('id') for _hh in hands
                                           if ((_hh.get('tournament') or '')[:30] == _v_tourney
                                               and _v_opener in (_hh.get('stacks_behind', {}) or {})
                                               and _hh.get('id') and _hh.get('id') != hid
                                               and _hh.get('vpip'))][:10]
                    if _ve_ids:
                        for _veid in _ve_ids:
                            _state._APPENDIX_HAND_IDS.add(_veid)
                            _state._register_hand_priority(_veid, 1)  # P1: villain evidence
                        _ve_str = ','.join(str(x) for x in _ve_ids[:10])
                        _ve_alias = _vi.get('alias', '') if _vi else ''
                        _ve_name = _ve_alias or _v_arch or 'this villain'
                        _ve_title = f'{_ve_name} — hands showing this pattern'
                        doc.w(f'  *Evidence:* <a class="hand-list-trigger" href="#" '
                              f'data-hids="{_ve_str}" '
                              f'data-list-title="{_html_escape(_ve_title)}">'
                              f'{len(_ve_ids)} hand{"s" if len(_ve_ids) != 1 else ""}'
                              f' vs {_ve_name}</a>')
                    doc.w("</details>")
                    doc.w("</div>")
                    doc.w("")
                    _has_notes_b = True

                # v8.7.0 PR2: Opponent context in yellow notes
                _vi_atoms = h.get('villain_evidence_atoms', []) or []
                _vi_exploits_oc = h.get('exploit_opportunities', []) or []
                if _vi_atoms or _vi_exploits_oc:
                    doc.w("<div class='opponent-context'>")
                    doc.w("<div class='oc-heading'>Opponent Evidence</div>")
                    # Group atoms by street
                    _oc_by_street = {}
                    for _atom in _vi_atoms:
                        _st = _atom.get('street', 'preflop')
                        _oc_by_street.setdefault(_st, []).append(_atom)
                    for _st in ('preflop', 'flop', 'turn', 'river'):
                        if _st not in _oc_by_street:
                            continue
                        doc.w(f"<p style='font-size:11px;font-weight:900;color:#6a4d00;"
                              f"text-transform:uppercase;letter-spacing:.05em;margin:6px 0 2px'>"
                              f"{_st.upper()}</p>")
                        for _atom in _oc_by_street[_st]:
                            _badge = _atom.get('badge', 'note')
                            _label = _atom.get('label', '')
                            _text = _atom.get('evidence_text', '')
                            _sig = _atom.get('signal', '')
                            _sig_label = _SIGNAL_LABELS_RENDER.get(_sig, _sig.replace('_', ' ').title() if _sig else '')
                            _ri = _atom.get('read_impact', '')
                            _title_attr = f' title="{_html_escape(_text)}"' if _text else ''
                            doc.w(f"<p><span class='vi-badge {_badge}'{_title_attr}>{_label}"
                                  f"{(' · ' + _sig_label) if _sig_label else ''}</span> "
                                  f"{_html_escape(_text)}"
                                  f"{'<br><em style=\"color:#6a4d00;font-size:12px\">Read impact: ' + _html_escape(_ri) + '</em>' if _ri else ''}</p>")
                    if _vi_atoms and not _vi_exploits_oc:
                        doc.w("<p style='font-size:11px;color:#94a3b8;margin-top:4px'>"
                              "<em>Tagging evidence — not necessarily a Hero mistake.</em></p>")
                    # Exploit implications
                    if _vi_exploits_oc:
                        doc.w(f"<div class='oc-heading' style='margin-top:8px'>Exploit Opportunity</div>")
                    for _exp in _vi_exploits_oc:
                        _elabel = _exp.get('label', '')
                        _etext = _exp.get('recommended_exploit', '')
                        _ebadge = _exp.get('badge', 'miss')
                        _ev_text = _exp.get('evidence_text', '')
                        _etitle_attr = f' title="{_html_escape(_ev_text)}"' if _ev_text else ''
                        doc.w(f"<p><span class='vi-badge {_ebadge}'{_etitle_attr}>{_elabel}</span> "
                              f"{_html_escape(_ev_text)}</p>")
                        if _etext:
                            doc.w(f"<p style='font-size:12px;color:#166534'>"
                                  f"<em>Recommended: {_html_escape(_etext)}</em></p>")
                    doc.w("</div>")
                    _has_notes_b = True

                # Auto-generated note for hands with NO other commentary.

                if not _has_notes_b:
                    _auto_parts = []
                    # Draw profile on key street
                    try:
                        from gem_made_hands import draw_profile as _dp_auto
                        _board_b = h.get('board') or []
                        if hero_cards_list and len(hero_cards_list) == 2 and _board_b:
                            # Use the last street with a board
                            _n_cards = min(len(_board_b), 5)
                            _dp_result = _dp_auto(hero_cards_list, _board_b[:_n_cards])
                            # v8.12.8 QA: engine-degraded sentinel is
                            # diagnostics, not prose — keep it out of notes
                            if (_dp_result and _dp_result.get('summary')
                                    and 'unavailable'
                                    not in _dp_result['summary']):
                                _auto_parts.append(_dp_result['summary'])
                    except Exception:
                        pass
                    # Action summary
                    _act_sum = h.get('action_summary', '')
                    if _act_sum:
                        _auto_parts.append(_act_sum[:80])
                    # Net result
                    if net_bb != 0:
                        _auto_parts.append(f"net {net_bb:+.1f}BB")
                    # A10: preflop-only hands — add context even with no board
                    if not _auto_parts:
                        _pf_parts = []
                        if pos and pos != '?':
                            _pf_parts.append(pos)
                        if stack_bb:
                            _pf_parts.append(f"{stack_bb:.0f}BB")
                        _pf_act = h.get('pf_action', '') or h.get('line_actions', '')
                        if _pf_act:
                            _pf_parts.append(_pf_act[:40])
                        elif h.get('pf_allin'):
                            _pf_parts.append('preflop all-in')
                        else:
                            _pf_parts.append('preflop')
                        if net_bb != 0:
                            _pf_parts.append(f"net {net_bb:+.1f}BB")
                        _auto_parts = _pf_parts
                    if _auto_parts:
                        doc.w("<div class='analyst-notes'>")
                        doc.w(f"📋 {' · '.join(_auto_parts)}")
                        doc.w("</div>")
                        doc.w("")

                # v8.14.1 rev-4 (Blocker D): explicit PKO-unavailable note for a
                # BOUNTY all-in with unresolved collectibility that got neither a
                # pot-odds Bounty-trust strip nor a PKO pill (XIV.B parity).
                if (not _po_b and not _pko_ctx_b.get('enabled')
                        and h.get('format') == 'BOUNTY' and h.get('pf_allin')
                        and h.get('bounty_collectible') in (None, 'unknown')):
                    doc.w("<div class='analyst-notes' data-street='preflop'>")
                    doc.w("\U0001f3af **PKO bounty math:** cover/collectibility "
                          "unresolved from the HH export, so this verdict uses "
                          "chip-chart logic only. Review manually.")
                    doc.w("</div>")
                    doc.w("")

                # B168 (Ron 2026-05-24): inline audit review row after the hand.
                doc.w(f"<<REVIEWROW|hand|{hid}|Hand {hid_short} \u2014 "
                      f"{_combo_to_chart(hero_cards_list)}>>")
                doc.w("</article>")
            if _n_trimmed > 0:
                doc.w(f"<p class='xivb-trim-note' style='color:#64748b;font-size:12px;"
                      f"padding:8px 12px;border-top:1px solid #e2e8f0;margin-top:8px'>"
                      f"{_n_trimmed} additional hand(s) omitted for report size. "
                      f"Hand IDs are still available in the citing section above "
                      f"and in your poker client hand history.</p>")
            doc.w("</details>")
            doc.w("")

    # v8.8.7 (Ron 2026-06-08): HA3 budget-trimmed anchor stubs.
    # The HA3 priority budget planner (draft.py) can drop cited P2 hands from
    # appendix_hand_ids_all to cap report size. Those hands are still cited in
    # the body with a live `#sec-app-hand-X` link, so without a matching anchor
    # the post-render validator reports dead hand-ref links. Emit a minimal
    # anchor stub for each so every citation resolves (handAvailability=
    # 'budget_trimmed'). Stubs are ~0.2KB each vs ~2.5KB full cards, preserving
    # most of the budget saving while keeping links honest.
    # Emit a stub for EVERY budget-trimmed hand, not only those in the
    # citation registry: some sections (e.g. Issue Explorer rep-tables) emit
    # `#sec-app-hand-X` links directly without going through _record_citation,
    # so filtering on _CITATIONS alone leaves those links dead.
    _trimmed = sorted(set(getattr(_state, '_BUDGET_TRIMMED_IDS', set()) or set()))
    # v8.16.2 Phase B: never emit a budget-trimmed STUB for a hand that already
    # received a FULL card in XIV.A/XIV.B. A trimmed needs_review hand can still
    # be rendered full by XIV.A (it reads needs_review directly, not the budgeted
    # appendix_hand_ids_all), so without this guard the hand appears BOTH as a
    # full lazy card and a budget_trimmed stub (the validator's "Issue 3"
    # double-render). Match on the 8-digit suffix used by both surfaces.
    _full_card_ids = set(getattr(_state, '_FULL_CARD_IDS', set()) or set())
    _cited_trimmed = [t for t in _trimmed
                      if (t[-8:] if len(t) > 8 else t) not in _full_card_ids]
    if _cited_trimmed:
        doc.w("")
        doc.w("<details>")
        doc.w(f"<summary><strong>XIV.C Size-Trimmed Hands "
              f"({len(_cited_trimmed)})</strong> — cited above; full detail "
              f"omitted for report size</summary>")
        doc.w("")
        doc.w("*These hands are referenced in the sections above. Full hand "
              "grids were trimmed to keep the report under its size budget — "
              "the hand IDs remain available in your poker client.*")
        doc.w("")
        for hid in _cited_trimmed:
            hid_short = hid[-8:] if len(hid) > 8 else hid
            if not hid_short:
                continue
            h = hands_by_id.get(hid, {}) or {}
            pos = h.get('position', '?')
            stack_bb = h.get('stack_bb') or 0
            net_bb = h.get('net_bb') or 0
            if net_bb > 0:
                bb_html = f"<span class='hand-net-pos'>+{net_bb:.1f} BB</span>"
            elif net_bb < 0:
                bb_html = f"<span class='hand-net-neg'>{net_bb:.1f} BB</span>"
            else:
                bb_html = f"<span class='hand-net-neu'>0 BB</span>"
            cites = _state._get_citations_for(hid)
            _back = ''
            if cites:
                _a, _lbl = cites[0]
                _back = f" — <a href='#{_a}'>{_lbl} ↑</a>"
            doc.w(f"<article class='hand-detail-card budget-trimmed' "
                  f"data-hand-id='{hid_short}' data-availability='budget_trimmed'>")
            doc.w("<div class='mh-top'><div class='mh-title'>")
            doc.w(f"<<ANCHOR:sec-app-hand-{hid_short}>>")
            try:
                doc.w(f"##### Hand `{hid_short}` ({pos} {float(stack_bb):.1f}BB) "
                      f"· {bb_html}{_back}")
            except (TypeError, ValueError):
                doc.w(f"##### Hand `{hid_short}` ({pos}) · {bb_html}{_back}")
            doc.w("</div></div>")
            doc.w("")
            doc.w("*Full hand detail trimmed for report size.*")
            doc.w("</article>")
        doc.w("</details>")
        doc.w("")


# ============================================================
# BACK-COMPAT API SHIM
# ============================================================

