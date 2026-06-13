# -*- coding: utf-8 -*-
"""analyst_worklist_v1 — Slice E (feature/analyst-worklist-v1, 2026-06-13).

Turns the analyzer's candidate surfaces into ONE prioritized triage queue
for the LLM analyst pass. Produces *proposals*, never final verdicts.

Hard policies baked in (Ron 2026-06-13):
  - Revealed-hand / actual all-in equity is LUCK context only, never the
    decision basis (decision quality = Hero vs villain RANGE).
  - Marginal opens are NOT errors; a bottom-5% buffer applies to
    non-marginal opens. Marginal/buffer hands may only land in
    aggregate_only / drill_candidate / review_if_time — never must_review.
  - The monster-action detector is price/bounty/closing-action aware: a
    tiny extra call in a PKO Hero can collect is not a punt.
  - Most automation emits a proposal + reviewer question; only narrow
    deterministic spots are auto_clear.

NOT in scope (do not add here): report UX, Hand Review Queue wiring.
This module only builds + emits the JSON artifact.
"""
import re

from gem_chart_labels import chart_display_label

SCHEMA = "analyst_worklist_v1"

BUCKETS = ('must_review', 'review_if_time', 'aggregate_only',
           'auto_clear', 'drill_candidate')

# Candidate buckets we read, in rough descending review value.
_SOURCE_BUCKETS = ('punts', 'mistakes', 'all_in_review', 'big_river_calldowns',
                   'coolers', 'iii4_screening', 'read_dependent_screening',
                   'bust_audit', 'bestplay_screening', 'blindspot_sample')

_RANK_VAL = {r: i for i, r in enumerate('23456789TJQKA', 2)}

_PREMIUM_GETIN = {'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88',
                  'AKs', 'AKo', 'AQs', 'AQo', 'AJs', 'KQs'}


def _hand_label(cards):
    """'4hAs'/['4h','As'] -> 'A4o', 'JcJd' -> 'JJ'. Chart notation for
    preflop reasoning; raw cards (with suits) are kept separately."""
    if isinstance(cards, (list, tuple)):
        cs = ''.join(str(x) for x in cards).replace(' ', '')
    else:
        cs = (cards or '').replace(' ', '')
    if len(cs) != 4:
        return cs
    r0, s0, r1, s1 = cs[0], cs[1], cs[2], cs[3]
    if _RANK_VAL.get(r1, 0) > _RANK_VAL.get(r0, 0):
        r0, s0, r1, s1 = r1, s1, r0, s0
    if r0 == r1:
        return r0 + r1
    return r0 + r1 + ('s' if s0 == s1 else 'o')


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _short(hid):
    return hid[-8:] if isinstance(hid, str) and len(hid) > 8 else hid


def _line_from_ledger(hand, decision_street):
    """v8.12.11 (GPT-5): build a real compact action line from the hand's
    action_ledger up to & including the decision street, so the analyst can
    reason without opening the replay. Marks Hero. Returns '' if no ledger."""
    if not hand:
        return ''
    led = hand.get('action_ledger') or []
    if not led:
        return ''
    hero = hand.get('hero', 'Hero')
    order = ['preflop', 'flop', 'turn', 'river']
    stop = order.index(decision_street) if decision_street in order else 3
    keep = set(order[:stop + 1])
    parts = []
    for a in led:
        st = a.get('street')
        if st not in keep:
            continue
        act = a.get('action', '')
        if act == 'posts':
            continue
        who = 'Hero' if a.get('player') == hero else (a.get('position') or '?')
        amt = a.get('amount_bb')
        seg = f"{who} {act}"
        if act in ('raises', 'bets', 'calls') and amt:
            seg += f" {_f(amt):.1f}"
        if a.get('is_all_in'):
            seg += " all-in"
        parts.append(seg)
    if not parts:
        return ''
    # mark street boundaries lightly so the analyst sees the structure
    return ' | '.join(parts)[:300]


def _canonical_action_line(c, hand=None):
    """Compact street-by-street line so the LLM reasons without the replay.
    Prefer a real ledger walk; fall back to the parser's line_actions; only
    then the terse action_summary (GPT-5: 'preflop_only' is not enough)."""
    dm = c.get('decision_math') or {}
    street = dm.get('key_decision_street') or (
        'preflop' if c.get('pf_allin') else 'flop')
    led_line = _line_from_ledger(hand, street)
    if led_line:
        return led_line
    for k in ('line_actions', 'action_sequence'):
        v = c.get(k)
        if isinstance(v, str) and v.strip() and v.strip() != 'preflop_only':
            return v.strip()[:300]
        if isinstance(v, list) and v:
            return ', '.join(str(x) for x in v)[:300]
    base = (c.get('action_summary') or '').strip()
    pos = c.get('position') or '?'
    cards = c.get('cards') or ''
    return (f"{pos} {cards}: {base}".strip(' :') or 'action unavailable')[:300]


def _decision_effective_bb(c):
    """Minimum-D prereq: effective stack vs the RELEVANT decision villain,
    not the table/hand nominal. For an all-in this is min(hero, jammer);
    otherwise the parser's at-decision effective stack."""
    hero = (_f(c.get('eff_stack_at_decision_bb'))
            or _f(c.get('effective_stack_bb'))
            or _f(c.get('stack_bb')))
    jam = _f(c.get('jammer_stack_bb'))
    if c.get('pf_allin') and jam > 0:
        return round(min(hero, jam) if hero > 0 else jam, 1)
    return round(hero, 1)


def _decision_node(c):
    dm = c.get('decision_math') or {}
    street = dm.get('key_decision_street') or (
        'preflop' if c.get('pf_allin') else 'flop')
    stblock = (dm.get('streets') or {}).get(street, {}) or {}
    facing = ''
    if c.get('pf_allin') and c.get('jammer_position'):
        facing = f"{c['jammer_position']} jam"
    elif stblock.get('villain_bet_bb'):
        facing = f"bet {_f(stblock.get('villain_bet_bb')):.1f}BB"
    eff = _decision_effective_bb(c)
    call_bb = (_f(stblock.get('hero_call_amount_bb'))
               or _f(c.get('hero_committed_bb')) or None)
    # v8.12.11 (GPT-4): a call can never exceed Hero's effective stack. When
    # the source value is the uncapped villain bet (> eff) or absent, the
    # capped call price is unknown -> null it (a downstream failure mode is
    # added) rather than render an impossible "call 130BB at 17BB eff".
    price_unavailable = False
    if call_bb and eff and call_bb > eff * 1.05:
        call_bb = None
        price_unavailable = True
    elif not call_bb:
        price_unavailable = True
    pos = c.get('position') or ''
    closing = bool(pos == 'BB' and not c.get('hero_3bet'))
    return {
        'street': street,
        'hero_action_facing': facing or 'unknown',
        'hero_actual_action': (stblock.get('hero_action')
                               or c.get('action_summary', '')[:40]),
        'call_amount_bb': round(call_bb, 1) if call_bb else None,
        'price_unavailable': price_unavailable,
        'effective_bb_vs_relevant_villain': eff,
        'players_behind': None,           # needs full ledger; left explicit
        'closing_action': closing,
    }


def _range_membership(c, dev, dev_charts):
    """Preflop chart membership. Marginal flag drives the no-error policy."""
    if not dev:
        return None
    chart_id = dev.get('chart') or ''
    conf = (dev.get('confidence') or '').upper()
    dtype = (dev.get('type') or '')
    is_marginal = conf in ('MARGINAL', 'EXTENDED', 'LOW')
    # Missed Open: CLEAR=core, MARGINAL=extended/bottom. Wide=too-wide.
    if 'Missed' in dtype:
        status = 'inside_core' if conf == 'CLEAR' else 'inside_extended'
    elif 'Wide' in dtype:
        status = 'outside_core'
    else:
        status = 'flagged'
    return {
        'chart_id': chart_id,                      # debug/source only
        'display_label': chart_display_label(chart_id),
        'hero_hand_status': status,
        'is_marginal': is_marginal,
        'bottom_5pct_buffer_applied': is_marginal,
    }


def _bounty_context(c, pko):
    """v8.12.11 (GPT-6): split the three orthogonal facts so the reader never
    sees 'adjustment applied' while collectibility is unknown:
      - estimated_bounty_exists : the model has a $/BB estimate
      - collectibility_known    : do we know whether Hero covers the villain
      - adjustment_applied_to_decision : a discount was applied AND coverage
        is known AND Hero covers (a flat discount_pp alone is NOT enough)."""
    fmt = (c.get('format') or '').upper()
    is_pko = fmt in ('BOUNTY', 'PKO', 'MYSTERY_BOUNTY')
    if not is_pko:
        return {'is_pko': False, 'hero_covers_relevant_villain': None,
                'collectibility_known': False, 'estimated_bounty_exists': False,
                'estimated_bounty_bb': None,
                'adjustment_applied_to_decision': False,
                'reason': 'non_bounty_format'}
    covers = None
    reason = 'collectibility_unknown'
    if pko and 'can_collect_bounty' in pko:
        covers = bool(pko.get('can_collect_bounty'))
        reason = (pko.get('coverage_label') or '')[:80] or (
            'hero_covers_relevant_villain' if covers else 'villain_covers_hero')
    est = (_f(pko.get('bounty_value_bb_est')) if pko else 0) or \
        _f(c.get('bounty_value_bb'))
    collectibility_known = covers is not None
    discount_flagged = _f(c.get('bounty_discount_pp')) > 0
    return {
        'is_pko': True,
        'estimated_bounty_exists': bool(est),
        'estimated_bounty_bb': round(est, 1) if est else None,
        'collectibility_known': collectibility_known,
        'hero_covers_relevant_villain': covers,
        # only TRUE when we KNOW Hero covers AND a discount is in play
        'adjustment_applied_to_decision': bool(
            discount_flagged and collectibility_known and covers),
        'reason': reason,
    }


def _source_truth(c, pko, dev):
    return {
        'price_engine': ('pot_odds_v8_12' if (c.get('pot_odds')
                         or (c.get('decision_math') or {}).get('streets'))
                         else 'none'),
        'stack_engine': 'decision_effective_stack',
        'range_engine': ('preflop_chart_registry' if dev else
                         'pko_research' if pko else 'none'),
        'villain_engine': ('villain_intel_v8'
                           if c.get('villain_archetype') else 'none'),
    }


# ---------------------------------------------------------------------------
# classification (policy-gated proposal + bucket)
# ---------------------------------------------------------------------------
def _is_monster_action(c):
    """Open + jam + cold-call before Hero, or Hero facing jam+caller. Hero
    did not initiate the all-in. Best-effort from available fields."""
    return bool(c.get('pf_allin') and c.get('jammer_position')
                and not c.get('pfr', False) is True and c.get('cold_called'))


def _pot_is_multiway(c):
    """v8.12.11 (GPT-3 follow-up): True iff 3+ players contested the pot
    (side-pot / field-equity ambiguity). Uses the all-in decomposition
    (n_opponents >= 2 -> Hero + 2 = 3-way) or postflop entrants
    (players_at_flop >= 3). NEVER n_players -- that is the table seat count
    (e.g. 6 at a 6-max table), which would flag every hand as multiway."""
    md = c.get('multiway_decomposition') or {}
    n_opp = md.get('n_opponents')
    if isinstance(n_opp, (int, float)) and n_opp >= 2:
        return True
    if int(_f(c.get('players_at_flop'), 0)) >= 3:
        return True
    return bool(c.get('multiway_pot'))


def _auto_clear_gate(c, dn, rng, bnt, dm_block, src_truth, action_line,
                     bestplay_only, is_premium, eff):
    """v8.12.11 (GPT-3): narrow, multi-condition gate for auto_clear on an
    all-in. ALL guards must pass; returns (ok, block_reason). The previous
    rule (bestplay_only and (premium or eff<=22)) cleared deep premiums
    (AKo 100BB, QQ 42BB) and any short non-premium (Q5s 13BB, A4o 18BB) —
    none of which are deterministic. The new gate requires a known node,
    real engines, decision-basis evidence, no multiway/side-pot/bounty/ICM
    ambiguity, and ONE positive basis (explicit chart / equity cushion /
    narrow premium short-stack)."""
    if not bestplay_only:
        return False, 'not_screened_clean'
    # req: no ICM / satellite / bubble overlay
    if (c.get('tournament_phase') or '') in ('bubble', 'ft_bubble'):
        return False, 'icm_overlay'
    if (c.get('format') or '').upper() == 'SATELLITE':
        return False, 'satellite_overlay'
    # req: no monster-action ambiguity
    if _is_monster_action(c):
        return False, 'monster_action'
    # req: no multiway / side-pot uncertainty
    if _pot_is_multiway(c):
        return False, 'multiway'
    if c.get('side_pot') or c.get('has_side_pot'):
        return False, 'side_pot'
    # req: bounty must be certain (PKO -> collectibility known)
    if bnt.get('is_pko') and not bnt.get('collectibility_known'):
        return False, 'bounty_uncertain'
    # req: known action node (price available + facing known) OR a rich,
    # ledger-built action line the analyst can read end-to-end.
    rich_line = bool(action_line and '|' in action_line)
    known_node = (not dn.get('price_unavailable')
                  and dn.get('hero_action_facing') != 'unknown')
    if not (known_node or rich_line):
        return False, 'unknown_node'
    # req: a real price engine must back the decision (never clear on no price)
    if src_truth.get('price_engine') == 'none':
        return False, 'price_engine_none'
    # req: ONE positive qualifying basis. Each is decision-basis evidence that
    # is NOT the revealed hand: chart membership, a computed range-equity
    # cushion, or the push/fold-standard premium short-stack class.
    explicit_chart = bool(rng and not rng.get('is_marginal')
                          and rng.get('hero_hand_status') in (
                              'inside_core', 'inside_extended'))
    cushion = False
    req, heq = dm_block.get('required_equity'), dm_block.get('hero_equity_vs_range')
    if req is not None and heq is not None:
        rv = _f(req); rv = rv * 100 if rv <= 1.5 else rv
        hv = _f(heq); hv = hv * 100 if hv <= 1.5 else hv
        cushion = hv >= rv + 8.0
    narrow_premium_short = bool(is_premium and eff and eff <= 20)
    if not (explicit_chart or cushion or narrow_premium_short):
        return False, 'no_qualifying_basis'
    return True, None


def _classify(c, dn, rng, bnt, dm_block, sources, src_truth, action_line):
    """Returns (bucket, auto_proposal, auto_confidence, finality,
    failure_modes, reviewer_question, why_review, dedupe_group, priority)."""
    cards = _hand_label(c.get('cards')) or 'this hand'
    pos = c.get('position') or '?'
    fm = []
    # "Best-play-only" = screened as a clean play with no error/cooler flag.
    bestplay_only = (sources == ['bestplay_screening'])
    is_premium = _hand_label(c.get('cards')) in _PREMIUM_GETIN

    # --- policy 1: marginal opens are NOT errors -------------------------
    if rng and rng['is_marginal'] and rng['hero_hand_status'] in (
            'inside_extended', 'flagged'):
        grp = ('missed_%s_extended_open' % pos
               if 'open' in (rng['display_label'] or '').lower()
               else 'marginal_preflop')
        return ('aggregate_only', 'Aggregate only', 'low', 'aggregate_only',
                ['bottom-of-range / extended hand'],
                f"{cards} is bottom-of-range ({rng['display_label']}); "
                "confirm it is NOT graded an error.",
                f"Marginal open/defend ({rng['display_label']}) — bottom-5% "
                "buffer applied; not an error.",
                grp, 18)

    # --- monster-action all-ins (price/bounty/closing aware) -------------
    if c.get('pf_allin'):
        req = _f(dm_block.get('required_equity')) * (
            100 if _f(dm_block.get('required_equity')) <= 1.5 else 1)
        heq = dm_block.get('hero_equity_vs_range')
        heq = (heq * 100 if heq is not None and heq <= 1.5 else heq)
        call_bb = dn.get('call_amount_bb') or 0
        eff = dn.get('effective_bb_vs_relevant_villain') or 0
        risked_pct = (call_bb / eff * 100) if (call_bb and eff) else 0
        tiny = (call_bb and call_bb <= 2.0) or (risked_pct and risked_pct <= 8)
        covers = bnt.get('hero_covers_relevant_villain')
        # collectible_tiny also demands a certain bounty + no side-pot/multiway
        collectible_tiny = bool(
            tiny and bnt.get('is_pko') and covers
            and not _pot_is_multiway(c)
            and not (c.get('side_pot') or c.get('has_side_pot')))
        grp = 'monster_action_allin' if _is_monster_action(c) else 'pf_allin'
        rq = (f"Do not use the revealed hand as the verdict basis. Decide "
              f"whether {cards} {pos} has enough equity vs the jamming/"
              f"calling RANGE at {eff:.0f}BB"
              + (f" (need ~{req:.0f}%)." if req else "."))
        if collectible_tiny:
            return ('auto_clear', 'Justified', 'medium', 'auto_clear',
                    ['range could still dominate if not truly tiny'],
                    rq, f"Tiny PKO call ({call_bb:.1f}BB) Hero can collect — "
                    "price/bounty make it standard.", grp, 22)
        if _is_monster_action(c) and not tiny:
            fm = ['range may be wider than assumed', 'bounty overlay',
                  'side-pot geometry']
            return ('must_review', 'Review required', 'medium',
                    'analyst_required', fm, rq,
                    f"Monster-action stack-off: jam + cold-call, Hero risks "
                    f"{call_bb:.1f}BB ({risked_pct:.0f}% stack).", grp, 72)
        # standard get-in -> auto_clear ONLY through the narrow multi-condition
        # gate (GPT-3): known node, real engines, decision-basis evidence, no
        # ICM/multiway/side-pot/bounty ambiguity, and a positive qualifying
        # basis. Deep premiums and short non-premiums no longer slip through.
        ac_ok, ac_block = _auto_clear_gate(
            c, dn, rng, bnt, dm_block, src_truth, action_line,
            bestplay_only, is_premium, eff)
        if ac_ok:
            return ('auto_clear', 'Justified', 'medium', 'auto_clear',
                    ['range could dominate if villain very tight'], rq,
                    f"Standard get-in: {cards} {pos} at {eff:.0f}BB inside the "
                    "jam/continue range — result is variance.", grp, 24)
        # ordinary all-in: range equity decides; revealed result is luck. If
        # the auto_clear gate blocked on a specific ambiguity, name it.
        fm = ['range model confidence low']
        if ac_block and ac_block not in ('not_screened_clean', 'no_qualifying_basis'):
            fm.append('auto_clear blocked: ' + ac_block)
        return ('review_if_time', 'Review required', 'low', 'analyst_required',
                fm, rq,
                f"All-in {pos} {cards} at {eff:.0f}BB — verify range equity "
                "vs threshold (result was luck, not the basis).",
                grp, 48)

    # --- Wide / Missed BB defend (chart-backed) --------------------------
    if rng and rng['hero_hand_status'] == 'outside_core':
        return ('review_if_time', 'Review required', 'medium',
                'analyst_required', ['pot odds / bounty may justify'],
                f"Is {cards} genuinely too wide for {rng['display_label']}, "
                "or do price/bounty/reads justify it?",
                f"Possible too-wide defend/open ({rng['display_label']}).",
                'wide_%s' % pos, 40)
    if rng and rng['hero_hand_status'] == 'inside_core':
        return ('must_review', 'Mistake', 'medium', 'analyst_required',
                ['ICM/satellite may excuse the fold'],
                f"{cards} is inside the core {rng['display_label']}; confirm "
                "the fold is a real leak and not ICM-driven.",
                f"Missed core open/defend ({rng['display_label']}).",
                'missed_core_%s' % pos, 60)

    # --- coolers: justified variance, low learning -----------------------
    if c.get('auto_verdict') == 'cooler_detected' or 'cooler' in (
            c.get('suggested_outcome') or ''):
        return ('aggregate_only', 'Cooler', 'medium', 'aggregate_only',
                [], "Confirm this is a structural cooler, not a leak.",
                "Cooler — both players committed strong; review only for "
                "closure.", 'cooler', 20)

    # --- postflop / river calldowns + leftover candidates ----------------
    if c.get('went_to_sd') and not c.get('pf_allin') and _f(c.get('net_bb')) < -8:
        return ('review_if_time', 'Review required', 'low', 'analyst_required',
                ['villain may value-bet worse', 'blocker effects'],
                f"River decision with {cards}: does villain's line have "
                "enough bluffs to justify the call/bet?",
                "Large postflop calldown/showdown loss.",
                'postflop_calldown', 44)

    # --- default: low-signal screening -> drill/aggregate ----------------
    return ('drill_candidate', 'Aggregate only', 'low', 'aggregate_only',
            [], f"Optional drill: {cards} {pos}.",
            "Low-signal screening candidate.", 'low_signal', 10)


# ---------------------------------------------------------------------------
# main builder
# ---------------------------------------------------------------------------
def build_analyst_worklist(candidates, stats, report_data, hands,
                           date_compact, runtime='v8.12.11'):
    candidates = candidates or {}
    stats = stats or {}
    report_data = report_data or {}
    pko_by_hand = (report_data.get('pko_research') or {}).get('by_hand', {})
    pot_odds_by_hand = report_data.get('pot_odds_by_hand') or {}
    devs_by_hand = {}
    for d in (stats.get('preflop_deviations') or []):
        if isinstance(d, dict) and d.get('id'):
            devs_by_hand.setdefault(d['id'], d)  # first wins
    dev_charts = stats.get('_dev_charts') or {}
    hands_by_id = {h.get('id'): h for h in (hands or []) if h.get('id')}
    reviewed = {hid for hid in (report_data.get('analyst_commentary') or {})
                if not str(hid).startswith('__')}

    # dedupe across buckets: first ctx wins, record all source buckets
    ctx_by_id, sources_by_id = {}, {}
    for bk in _SOURCE_BUCKETS:
        for c in (candidates.get(bk, []) or []):
            if not (isinstance(c, dict) and c.get('id')):
                continue
            hid = c['id']
            sources_by_id.setdefault(hid, []).append(bk)
            ctx_by_id.setdefault(hid, c)

    items = {}
    for hid, c in ctx_by_id.items():
        if hid in reviewed:
            continue  # default worklist excludes already-reviewed hands
        pko = pko_by_hand.get(hid) or pko_by_hand.get(_short(hid)) or {}
        pko = pko if pko.get('enabled') else {}
        dev = devs_by_hand.get(hid)
        dm_block = ((c.get('decision_math') or {}).get('streets') or {}).get(
            (c.get('decision_math') or {}).get('key_decision_street', ''), {})
        dn = _decision_node(c)
        rng = _range_membership(c, dev, dev_charts)
        bnt = _bounty_context(c, pko)
        action_line = _canonical_action_line(c, hands_by_id.get(hid))
        src_truth = _source_truth(c, pko, dev)
        (bucket, proposal, conf, finality, fmodes, rq, why, grp,
         prio) = _classify(c, dn, rng, bnt, dm_block,
                           sources_by_id.get(hid, []), src_truth, action_line)
        # v8.12.11 (GPT-4): surface the unavailable-price failure mode wherever
        # the decision node could not produce a capped call amount.
        if dn.get('price_unavailable') and 'decision price unavailable' not in fmodes:
            fmodes = fmodes + ['decision price unavailable']

        po = pot_odds_by_hand.get(hid) or pot_odds_by_hand.get(_short(hid)) or {}
        items[hid] = {
            'hand_id': hid,
            'priority': prio,
            'bucket': bucket,
            'candidate_sources': sources_by_id.get(hid, []),
            'hero_cards': c.get('cards', ''),          # raw, suits preserved
            'hero_hand_label': _hand_label(c.get('cards')),  # chart notation
            'hero_pos': c.get('position', ''),
            'effective_bb': dn['effective_bb_vs_relevant_villain'],
            'street': dn['street'],
            'spot_label': (pko.get('spot') or rng and rng['display_label']
                           or c.get('action_summary', '')[:60] or 'spot'),
            'tournament_context': {'format': c.get('format', ''),
                                   'phase': c.get('tournament_phase', '')},
            'canonical_action_line': action_line,
            'decision_node': dn,
            'range_membership': rng,
            'bounty_context': bnt,
            'source_truth': src_truth,
            'auto_proposal': proposal,
            'auto_confidence': conf,
            'finality': finality,
            'evidence': _evidence(c, po, dm_block, pko),
            'failure_modes': fmodes,
            'reviewer_question': rq,
            'llm_prompt_hint': rq,
            'why_review': why,
            'dedupe_group': grp,
            'report_anchor': '#sec-app-hand-' + _short(hid),
            'review_outcome': {
                'status': 'unreviewed', 'final_verdict': None,
                'confidence': None, 'user_facing_summary': None,
                'should_show_in_report': None,
            },
        }

    # dedupe-group caps: at most 3 must_review per group; overflow → aggregate
    _demote_group_overflow(items, cap=3)

    buckets = {b: [] for b in BUCKETS}
    for hid, it in sorted(items.items(),
                          key=lambda kv: (-kv[1]['priority'], kv[0])):
        buckets[it['bucket']].append(hid)

    return {
        'schema': SCHEMA,
        'session': date_compact,
        'runtime': runtime,
        'generated_counts': {b: len(v) for b, v in buckets.items()},
        'reviewed_excluded': len(reviewed),
        'buckets': buckets,
        'items': items,
    }


def _evidence(c, po, dm_block, pko):
    ev = []
    if dm_block.get('required_equity') is not None:
        rq = _f(dm_block['required_equity'])
        ev.append('required equity %.0f%%' % (rq * 100 if rq <= 1.5 else rq))
    if dm_block.get('hero_equity_vs_range') is not None:
        hq = _f(dm_block['hero_equity_vs_range'])
        ev.append('hero vs range %.0f%%' % (hq * 100 if hq <= 1.5 else hq))
    if po.get('required_eq_pct') is not None:
        ev.append('pot-odds need %.1f%%' % _f(po['required_eq_pct']))
        if po.get('is_overbet'):
            ev.append('OVERBET %s%% pot' % po.get('bet_pct_of_pot', '?'))
    if c.get('hero_realized_eq_at_allin') is not None:
        ev.append('result equity %.0f%% (luck only, not the basis)'
                  % _f(c['hero_realized_eq_at_allin']))
    if pko.get('pko_delta_pp') is not None:
        ev.append('PKO Δ %+.1fpp aggregate' % _f(pko['pko_delta_pp']))
    if c.get('villain_archetype_label'):
        ev.append('villain read: ' + str(c['villain_archetype_label']))
    return ev


def _demote_group_overflow(items, cap=3):
    """Keep dedupe groups from flooding must_review: beyond `cap` per group,
    demote the lowest-priority extras to aggregate_only."""
    from collections import defaultdict
    by_grp = defaultdict(list)
    for hid, it in items.items():
        if it['bucket'] == 'must_review':
            by_grp[it['dedupe_group']].append(hid)
    for grp, hids in by_grp.items():
        if len(hids) <= cap:
            continue
        hids.sort(key=lambda h: -items[h]['priority'])
        for h in hids[cap:]:
            items[h]['bucket'] = 'aggregate_only'
            items[h]['why_review'] += ' (aggregated — repeated group)'
