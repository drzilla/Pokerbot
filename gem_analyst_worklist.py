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
# v8.13.1 P1: the two loss-coverage screens are appended LAST so a hand that is
# already a punt/mistake/cooler/bust keeps its richer classification (first ctx
# wins in dedup), while a hand that reached the worklist ONLY via a loss screen
# is still force-reviewed via _classify's screen branch.
_SOURCE_BUCKETS = ('punts', 'mistakes', 'all_in_review', 'big_river_calldowns',
                   'coolers', 'iii4_screening', 'read_dependent_screening',
                   'bust_audit', 'bestplay_screening', 'blindspot_sample',
                   'biggest_loss_screen', 'postflop_loss_screen')

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


# ---------------------------------------------------------------------------
# decision kind / basis (GPT review #2: align the reviewed decision)
# ---------------------------------------------------------------------------
# A worklist item reviews ONE decision. Its kind decides which street the
# decision_node, canonical_action_line, and effective stack anchor to. A
# preflop chart/range deviation must NEVER inherit a later-street node or a
# full-hand action line.
_PREFLOP_KINDS = ('preflop_deviation', 'preflop_allin')


def _decision_kind(c, dev):
    if dev is not None:
        return 'preflop_deviation'   # chart/range deviation IS the decision
    if c.get('pf_allin'):
        return 'preflop_allin'
    if c.get('went_to_sd'):
        return 'postflop_call_fold'
    if c.get('villain_archetype'):
        return 'villain_exploit'
    return 'low_signal_drill'


def _is_preflop_kind(kind):
    return kind in _PREFLOP_KINDS


def _preflop_effective_bb(c, dev):
    """Clean effective stack for a PREFLOP decision: the deviation's recorded
    stack, else the hand-nominal stack. Deliberately NOT
    eff_stack_at_decision_bb, which can be overwritten by a later all-in that
    happened AFTER Hero's preflop action (the K6s first-in-open bug)."""
    s = _f(dev.get('stack_bb')) if dev else 0.0
    if not s:
        s = _f(c.get('effective_stack_bb')) or _f(c.get('stack_bb'))
    return round(s, 1)


def _fmt_action(a):
    """'raises 1.2', 'calls 8.6 all-in', 'folds', ''. Takes a ledger entry."""
    if not a:
        return ''
    act = a.get('action', '')
    seg = act
    amt = a.get('amount_bb')
    if act in ('raises', 'bets', 'calls') and amt:
        seg += ' %.1f' % _f(amt)
    if a.get('is_all_in'):
        seg += ' all-in'
    return seg


def _hero_preflop_action(hand, which='first'):
    """Hero's first (default) or last voluntary preflop action as a string.
    Deviations are graded on Hero's FIRST action (the open/call/fold); a
    preflop all-in is graded on Hero's LAST action (the jam / call-off)."""
    if not hand:
        return ''
    hero = hand.get('hero', 'Hero')
    acts = [a for a in (hand.get('action_ledger') or [])
            if a.get('street') == 'preflop' and a.get('action') != 'posts'
            and a.get('player') == hero]
    if not acts:
        return ''
    return _fmt_action(acts[-1] if which == 'last' else acts[0])


def _preflop_allin_event(hand):
    """v8.12.11 (GPT review #4): the reviewed event for a preflop all-in is
    Hero's LAST preflop action (the jam or call-off), NOT the first open.
    Returns (hero_action_entry, faced_entry, limped_before):
      - hero_action_entry: Hero's last preflop ledger entry
      - faced_entry: the LAST villain raise/all-in BEFORE it (what Hero faced)
      - limped_before: a villain limped (called) before Hero with no raise."""
    if not hand:
        return None, None, False
    hero = hand.get('hero', 'Hero')
    pf = [a for a in (hand.get('action_ledger') or [])
          if a.get('street') == 'preflop' and a.get('action') != 'posts']
    hero_idx = [i for i, a in enumerate(pf) if a.get('player') == hero]
    if not hero_idx:
        return None, None, False
    last = hero_idx[-1]
    faced, limped = None, False
    for a in pf[:last]:
        if a.get('player') == hero:
            continue
        if a.get('action') in ('raises', 'bets') or a.get('is_all_in'):
            faced = a
        elif a.get('action') == 'calls':
            limped = True
    return pf[last], faced, limped


def _allin_sizing(is_call, raw, eff, faced_amt, faced_allin, hero_allin):
    """v8.12.11 (GPT review #5): separate the RAW ledger commitment from the
    decision-effective stack so the worklist never shows a price/size above
    the effective stack without an overjam / side-pot explanation.

    Returns (call_amount_bb, price_unavailable, price_failure_reason, fields):
      fields = action_size_bb, decision_effective_bb, risk_bb, overjam_bb
      (+ jam_size_bb for a jam). decision_effective_bb is reconciled from
      Hero's all-in commitment when that is the authoritative number."""
    tol = 0.05
    raw = _f(raw); faced_amt = _f(faced_amt); eff = _f(eff)
    # An all-in CALL-OFF commits Hero's whole stack, so his side of the
    # effective stack IS raw. Reconcile against the villain's ALL-IN jam
    # (a non-all-in raise size is NOT the villain's stack). This fixes the
    # contaminated eff (88: 18.9 -> 23.7) without trusting eff_stack blindly.
    if is_call and hero_allin and raw and faced_allin and faced_amt:
        eff = round(min(raw, faced_amt), 1)
    eligible = round(min(raw, eff), 1) if (raw and eff) else (
        round(raw, 1) if raw else (round(eff, 1) if eff else None))
    big = max(raw, faced_amt)
    overjam = round(big - eligible, 1) if (eligible and big > eligible + tol) else None
    fields = {
        'action_size_bb': round(raw, 1) if raw else None,
        'decision_effective_bb': round(eff, 1) if eff else None,
        'risk_bb': eligible,
        'overjam_bb': overjam,
    }
    if not is_call:                       # Hero jams: no call price
        fields['jam_size_bb'] = round(raw, 1) if raw else None
        return None, False, None, fields
    if not raw:
        return None, True, 'decision price unavailable', fields
    if raw <= eff + tol:                  # within the effective stack: clean
        return round(raw, 1), False, None, fields
    if faced_amt and faced_amt + tol >= raw and eff:
        # clean overjam: a single villain shoved >= Hero's raw, so the
        # eligible price is Hero's effective stack; overjam_bb explains the gap.
        return round(eff, 1), False, None, fields
    # cannot reconcile (multiway / dead money / contaminated eff)
    return None, True, 'decision price requires side-pot/overjam reconciliation', fields


def _hero_faces_preflop_raise(hand):
    """v8.12.11 (GPT review #3): True iff a voluntary raise/all-in occurred
    BEFORE Hero's first preflop action — i.e. Hero is FACING a price (BB
    defend, cold-call, a re-jam spot, calling a jam). False = Hero is first-in
    (open / fold-first-in / open-jam) and faces NO call amount. None if there
    is no ledger to read (caller falls back to the first_in field)."""
    if not hand:
        return None
    hero = hand.get('hero', 'Hero')
    raised = False
    for a in (hand.get('action_ledger') or []):
        if a.get('street') != 'preflop' or a.get('action') == 'posts':
            continue
        if a.get('player') == hero:
            return raised            # decision reached
        if a.get('action') in ('raises', 'bets') or a.get('is_all_in'):
            raised = True
    return raised


def _hero_preflop_call_amount(hand):
    """The BB amount of Hero's preflop CALL (the price Hero actually faced),
    from the ledger. None if Hero's first preflop action was not a call."""
    if not hand:
        return None
    hero = hand.get('hero', 'Hero')
    for a in (hand.get('action_ledger') or []):
        if a.get('street') != 'preflop' or a.get('action') == 'posts':
            continue
        if a.get('player') == hero:
            if a.get('action') == 'calls':
                return _f(a.get('amount_bb')) or None
            return None
    return None


def _line_from_ledger(hand, decision_street, stop=None):
    """v8.12.11 (GPT-5): build a real compact action line from the hand's
    action_ledger up to & including the decision street, so the analyst can
    reason without opening the replay. Marks Hero. Returns '' if no ledger.

    `stop` controls where the line ends on the decision street so it never
    bleeds past the reviewed decision (GPT reviews #2/#4):
      - 'first': stop after Hero's FIRST action (preflop chart/range deviation)
      - 'last' : stop after Hero's LAST action (preflop all-in / call-off)
      - None   : full line through the decision street (postflop)."""
    if not hand:
        return ''
    led = hand.get('action_ledger') or []
    if not led:
        return ''
    hero = hand.get('hero', 'Hero')
    order = ['preflop', 'flop', 'turn', 'river']
    si = order.index(decision_street) if decision_street in order else 3
    keep = set(order[:si + 1])
    seq = [a for a in led if a.get('street') in keep and a.get('action') != 'posts']
    stop_i = None
    if stop in ('first', 'last'):
        hpos = [i for i, a in enumerate(seq)
                if a.get('player') == hero and a.get('street') == decision_street]
        if hpos:
            stop_i = hpos[0] if stop == 'first' else hpos[-1]
    parts = []
    for i, a in enumerate(seq):
        who = 'Hero' if a.get('player') == hero else (a.get('position') or '?')
        seg = f"{who} {a.get('action', '')}"
        amt = a.get('amount_bb')
        if a.get('action') in ('raises', 'bets', 'calls') and amt:
            seg += f" {_f(amt):.1f}"
        if a.get('is_all_in'):
            seg += " all-in"
        parts.append(seg)
        if stop_i is not None and i == stop_i:
            break   # reviewed decision made; do not read further
    if not parts:
        return ''
    return ' | '.join(parts)[:300]


def _canonical_action_line(c, hand=None, kind=None):
    """Compact street-by-street line so the LLM reasons without the replay.
    Prefer a real ledger walk; fall back to the parser's line_actions; only
    then the terse action_summary (GPT-5: 'preflop_only' is not enough).

    GPT review #2: a PREFLOP-kind item anchors to the preflop street; a
    preflop deviation additionally stops at Hero's preflop decision."""
    if _is_preflop_kind(kind):
        street = 'preflop'
        # deviation -> Hero's first action (the chart decision); all-in ->
        # Hero's last action (the jam / call-off commitment).
        stop = 'last' if kind == 'preflop_allin' else 'first'
    else:
        dm = c.get('decision_math') or {}
        street = dm.get('key_decision_street') or (
            'preflop' if c.get('pf_allin') else 'flop')
        stop = None
    led_line = _line_from_ledger(hand, street, stop=stop)
    if led_line:
        return led_line
    for k in ('line_actions', 'action_sequence'):
        v = c.get(k)
        if isinstance(v, str) and v.strip() and v.strip() != 'preflop_only':
            return v.strip()[:300]
        if isinstance(v, list) and v:
            return ', '.join(str(x) for x in v)[:300]
    # the whole-hand action_summary is misleading for a preflop deviation
    base = '' if _is_preflop_kind(kind) else (c.get('action_summary') or '').strip()
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


# v8.13.1 P1: short-shove depth. At or below this EFFECTIVE stack a preflop jam
# is standard short-stack shove territory, NOT a "deep overjam". A verdict that
# claims a deep overjam while the effective stack is this short is almost always
# confusing Hero's TOTAL stack with the effective stack vs live opponents
# (2026-06-13: Q8s SB jam, total 33.6BB / effective vs BB 18.0BB, was falsely
# flagged a 34BB overjam).
SHORT_SHOVE_MAX_BB = 25.0


def effective_stack_safety(hero_total_bb, eff_vs_opponents_bb, overjam_bb=None):
    """Pure / testable. Any shove / overjam / sizing-leak verdict must display
    Hero's TOTAL stack, the EFFECTIVE stack vs live opponents, and the depth the
    decision is evaluated at. Returns:
      {'hero_total_bb', 'effective_vs_opponents_bb', 'eval_depth_bb',
       'safety_line', 'warn'}
    eval_depth_bb is the EFFECTIVE stack (what the decision MUST be evaluated
    at). warn is True when a deep overjam is claimed at short-shove depth — the
    signal of total-vs-effective confusion."""
    total = _f(hero_total_bb)
    eff = _f(eff_vs_opponents_bb)
    oj = _f(overjam_bb)
    depth = eff if eff > 0 else total
    warn = bool(oj and oj > 0 and 0 < eff <= SHORT_SHOVE_MAX_BB)
    if total and eff and total > eff + 0.5:
        safety_line = (f"Hero stack {total:.1f}BB; effective vs live opponents "
                       f"{eff:.1f}BB -> evaluate as {eff:.0f}BB shove, not "
                       f"{total:.0f}BB overjam.")
    elif eff:
        safety_line = (f"Hero stack {total:.1f}BB; effective vs live opponents "
                       f"{eff:.1f}BB (equal) -> evaluate at {eff:.0f}BB.")
    else:
        safety_line = ''
    return {'hero_total_bb': round(total, 1) if total else None,
            'effective_vs_opponents_bb': round(eff, 1) if eff else None,
            'eval_depth_bb': round(depth, 1) if depth else None,
            'safety_line': safety_line,
            'warn': warn}


# v8.17.1 Iteration 1 (corrective): every worklist item resolves the SAME canonical
# decision snapshot — at the action this item REVIEWS — so its street/effective
# stack/action kind/bounty come from the one canonical model, never a separate algo.
def _reviewed_action_index(hand, kind):
    hero = (hand or {}).get('hero', 'Hero')
    led = (hand or {}).get('action_ledger') or []
    if not led:
        return None
    pf = [i for i, a in enumerate(led)
          if a.get('street') == 'preflop' and a.get('player') == hero and a.get('action') != 'posts']
    if kind == 'preflop_deviation':
        return pf[0] if pf else None         # the open / first voluntary action
    if kind == 'preflop_allin':
        return pf[-1] if pf else None        # the jam / call-off
    allh = [i for i, a in enumerate(led)
            if a.get('player') == hero and a.get('action') != 'posts']
    return allh[-1] if allh else None        # postflop: Hero's last action


def _canonical_snapshot(hand, kind):
    idx = _reviewed_action_index(hand, kind)
    if hand is None or idx is None:
        return None
    try:
        from gem_decision_snapshot import build_decision_snapshot
        return build_decision_snapshot(hand, idx)
    except Exception:
        return None


def _decision_node(c, kind=None, dev=None, hand=None):
    dm = c.get('decision_math') or {}
    preflop = _is_preflop_kind(kind)
    _csnap = _canonical_snapshot(hand, kind)   # ONE canonical snapshot for this item
    _cakind = _csnap.get('hero_action_kind') if _csnap else None
    # GPT review #2: a preflop-kind item anchors to preflop. Postflop items take the
    # canonical decision street (Hero's reviewed-action street) so a flop commitment
    # is never mislabelled a later street (the "River decision" flop-fixture bug).
    if preflop:
        street = 'preflop'
    elif _csnap and _csnap.get('street'):
        street = _csnap['street']
    else:
        street = dm.get('key_decision_street') or (
            'preflop' if c.get('pf_allin') else 'flop')
    stblock = (dm.get('streets') or {}).get(street, {}) or {}
    pos = c.get('position') or ''
    closing = bool(pos == 'BB' and not c.get('hero_3bet'))
    # v8.17.1 Iteration 1: a preflop chart deviation that is ALSO an all-in
    # confrontation (Hero calls / re-jams / over-jams / faces a jam off-chart)
    # must use the canonical DECISION-EFFECTIVE stack vs the faced aggressor,
    # NOT the clean full preflop stack — otherwise the worklist contradicts the
    # snapshot AND the report (83915520: A8o BTN calling a 9.6BB HJ open-jam is
    # a 9.6BB call-off, not a 22BB deviation). The snapshot's eff formula is the
    # SAME one the parser stamps into eff_stack_bb_at_decision, so worklist ==
    # report == snapshot. Only a genuine NON-all-in deviation (open / fold /
    # non-all-in 3-bet off-chart) keeps the clean preflop stack.
    _CANON_ALLIN_KINDS = ('call_vs_jam', 'call_off', 'open_shove',
                          'rejam_over_live_raise', 'overjam_with_side_pot')
    _allin_confront = (kind == 'preflop_allin') or (
        preflop and _cakind in _CANON_ALLIN_KINDS)
    # effective stack: preflop deviations keep the clean preflop stack; every other
    # kind takes the canonical snapshot's effective stack vs the faced aggressor
    # (84990829: 17.5BB vs the real raiser, NOT the 0.8BB dead-short side pot).
    if kind == 'preflop_deviation' and not _allin_confront:
        eff = _preflop_effective_bb(c, dev)
    else:
        _ceff = ((_csnap.get('effective_stack_vs_faced_aggressor')
                  or _csnap.get('max_effective_stack_among_active_opponents'))
                 if _csnap else None)
        eff = _ceff if _ceff is not None else _decision_effective_bb(c)

    # ===== preflop ALL-IN: anchor to Hero's reviewed event (GPT review #4) ===
    # The reviewed event is Hero's LAST preflop action — the jam or the
    # call-off — NOT the first open. A jam (Hero aggressor) carries no call
    # price; a call-off carries the actual capped call amount. v8.17.1 Iteration
    # 1: this runs for ANY canonical all-in confrontation (incl. a deviation-
    # bucketed call-of-jam like 83915520), so the node carries the capped call
    # price + decision-effective stack the snapshot/report use, not a 22BB price.
    if _allin_confront:
        evt, faced, limped = _preflop_allin_event(hand)
        if evt is not None:
            # v8.17.1 Iteration 1 (action kind from the ledger): a "raise" over a
            # villain who is ALREADY all-in is a CALL-OFF of that (short) jam, not a
            # re-jam — there is no live raise left to pressure and Hero's excess is
            # uncalled. The canonical action kind owns this distinction so the
            # reviewed event reads "call vs jam", carries the real capped call price,
            # and never implies fold equity that does not exist (83915520: A8o BTN
            # "raises 12.7 all-in" over a 9.6BB all-in jam == a call-off, not a rejam).
            akind = _cakind or 'open_shove'   # canonical, future-blind, at the reviewed index
            is_call = (evt.get('action') == 'calls') or (akind in ('call_vs_jam', 'call_off'))
            faced_amt = _f(faced.get('amount_bb')) if faced else 0.0
            faced_allin = bool(faced.get('is_all_in')) if faced else False
            hero_allin = bool(evt.get('is_all_in'))
            if faced is not None:
                fp = faced.get('position') or 'villain'
                fword = 'jam' if faced_allin else 'raise'
                facing = (f"{fp} {fword} {faced_amt:.1f}BB" if faced_amt
                          else f"{fp} {fword}")
            else:
                # Preserve the established deviation-path wording for a first-in
                # open-shove that is now routed through the unified all-in block.
                facing = ('vs limper(s)' if limped
                          else ('first-in (folds to Hero)'
                                if kind == 'preflop_deviation' else 'first-in'))
            # GPT review #5: split the raw ledger size from the decision-
            # effective stack; never show a price above the effective stack
            # without an overjam/side-pot explanation.
            call_bb, price_unavailable, price_fail, szf = _allin_sizing(
                is_call, _f(evt.get('amount_bb')), eff, faced_amt,
                faced_allin, hero_allin)
            # v8.17.1 Iteration 1: the canonical snapshot is authoritative for
            # the DISPLAYED effective stack and a call/call-off's price — the
            # jammer's TOTAL stack and Hero's to-call, NOT the jam INCREMENT
            # _allin_sizing reconciles against. 83915520: snapshot effective vs
            # the 9.6BB jammer == 9.6BB, to-call 9.3BB; _allin_sizing's
            # min(raw, jam-increment) reads 8.5BB / no price. Using the snapshot
            # here keeps worklist == report == snapshot (the parser stamps the
            # SAME eff). szf still owns the overjam / action-size split.
            _snap_eff = ((_csnap.get('effective_stack_vs_faced_aggressor')
                          or _csnap.get('max_effective_stack_among_active_opponents'))
                         if _csnap else None)
            _disp_eff = (round(_f(_snap_eff), 1) if _snap_eff
                         else (szf.get('decision_effective_bb') or eff))
            _snap_tocall = _csnap.get('to_call_bb') if _csnap else None
            # The 83915520 pattern: HEADS-UP, Hero RAISES ALL-IN over a SHORTER
            # all-in jam he COVERS (the canonical kind is call_vs_jam — vs the
            # jammer it is a call, the excess is returned). _allin_sizing
            # reconciles against the jam INCREMENT, so it reads a spurious
            # overjam and an unavailable price; the canonical snapshot owns the
            # real to-call and effective stack here. This narrow gate leaves a
            # SHORTER-stack call-off (Hero can't cover -> the villain's uncalled
            # excess IS a real overjam) and multiway side-pots on the existing
            # conservative _allin_sizing path untouched.
            _raw_amt = _f(evt.get('amount_bb'))
            _covering_call = bool(
                is_call and hero_allin and faced_allin and _raw_amt and faced_amt
                and _raw_amt >= faced_amt - 0.05 and not _pot_is_multiway(c))
            _px_from_snap = False
            if _covering_call and _snap_tocall and (call_bb is None or price_unavailable):
                call_bb = round(_f(_snap_tocall), 1)
                price_unavailable = False
                price_fail = None
                _px_from_snap = True
            if _covering_call:
                # Hero matches the jam and his raise excess is returned — no
                # overjam, no eff-stack warning on what is really a call.
                szf['overjam_bb'] = None
                szf['decision_effective_bb'] = _disp_eff
            # v8.12.12 Obj-C: price_engine provenance. A jam has no call price
            # (not_applicable); an unreconcilable price is unavailable; a capped
            # overjam call-off is sidepot_reconciled; otherwise the ledger.
            if not is_call:
                price_source = 'not_applicable'
            elif _px_from_snap:
                price_source = 'canonical_snapshot'
            elif price_unavailable:
                price_source = 'unavailable'
            elif szf.get('overjam_bb'):
                price_source = 'sidepot_reconciled'
            else:
                price_source = 'action_ledger'
            node = {
                'street': 'preflop', 'decision_kind': kind,
                'hero_action_kind': akind,
                'hero_action_facing': facing or 'unknown',
                'hero_actual_action': _fmt_action(evt),
                'call_amount_bb': call_bb,
                'price_unavailable': price_unavailable,
                'price_not_applicable': (not is_call),
                'price_failure_reason': price_fail,
                'price_source': price_source,
                'effective_bb_vs_relevant_villain': _disp_eff,
                'players_behind': None, 'closing_action': closing,
            }
            node.update(szf)
            # v8.13.1 P1: any shove/overjam/sizing verdict must DISPLAY Hero
            # total stack, the effective stack vs live opponents, and the eval
            # depth — and WARN when a deep overjam is claimed at short-shove
            # depth (the total-vs-effective confusion that mislabelled Q8s).
            _ess = effective_stack_safety(
                c.get('stack_bb'),
                _disp_eff,
                szf.get('overjam_bb'))
            node['hero_total_bb'] = _ess['hero_total_bb']
            node['effective_vs_opponents_bb'] = _ess['effective_vs_opponents_bb']
            node['eval_depth_bb'] = _ess['eval_depth_bb']
            node['eff_stack_safety_line'] = _ess['safety_line']
            node['eff_stack_warn'] = _ess['warn']
            if _ess['warn']:
                import sys as _sys_es
                print(f"  WARNING EFF-STACK: Hand {c.get('id')} overjam "
                      f"{szf.get('overjam_bb')}BB claimed at effective "
                      f"{_ess['effective_vs_opponents_bb']}BB "
                      f"(<= {SHORT_SHOVE_MAX_BB:.0f}BB short-shove) — verify "
                      f"Hero total vs effective.", file=_sys_es.stderr)
            return node
        # no ledger -> fall through to the generic logic (uses first_in etc.)

    # ===== generic (preflop deviation / postflop / no-ledger all-in) =========
    facing = ''
    if kind == 'preflop_deviation':
        # Use the ledger (authoritative) to decide first-in vs facing — the
        # candidate's opener_position can be a LATER raiser (e.g. an SB shove
        # after Hero already folded), so never trust it alone for a first-in.
        _faces = _hero_faces_preflop_raise(hand)
        if _faces is None:
            _faces = not bool(c.get('first_in'))
        opener = ((dev.get('opener_position') or dev.get('opener')) if dev else '') or ''
        if not _faces:
            facing = 'first-in (folds to Hero)'
        else:
            facing = f"{opener} open" if opener else 'facing a raise'
    elif c.get('pf_allin') and c.get('jammer_position'):
        facing = f"{c['jammer_position']} jam"
    elif stblock.get('villain_bet_bb'):
        facing = f"bet {_f(stblock.get('villain_bet_bb')):.1f}BB"
    # --- decision price (GPT review #3: kind/facing aware) ----------------
    # A call price exists ONLY when Hero faces a prior bet/raise. A first-in
    # open / fold-first-in / open-jam has NO call amount -> null + N/A.
    faces_raise = _hero_faces_preflop_raise(hand) if preflop else None
    if preflop and faces_raise is None:
        faces_raise = not bool(c.get('first_in'))   # no ledger: use first_in
    price_unavailable = False
    price_not_applicable = False
    price_source = ''                     # v8.12.12 Obj-C: provenance
    if preflop and not faces_raise:
        call_bb = None
        price_not_applicable = True
        price_source = 'not_applicable'   # first-in open/fold: no call price
    else:
        _stb = _f(stblock.get('hero_call_amount_bb'))
        _led = _hero_preflop_call_amount(hand) if preflop else None
        _com = _f(c.get('hero_committed_bb'))
        call_bb = _stb or _led or _com or None
        if call_bb and eff and call_bb > eff * 1.05:
            call_bb = None
            price_unavailable = True
            price_source = 'unavailable'
        elif not call_bb:
            price_unavailable = (not preflop)
            price_source = 'unavailable'   # a price was relevant but is missing
        elif _stb:
            price_source = ('pot_odds_v8_12' if (not preflop and c.get('pot_odds'))
                            else 'candidate_decision_math')
        else:                              # ledger call / committed amount
            price_source = 'action_ledger'
    if preflop and hand:
        hero_act = _hero_preflop_action(hand) or stblock.get('hero_action') or ''
    else:
        hero_act = (stblock.get('hero_action')
                    or c.get('action_summary', '')[:40])
    # REV2 B2/B6: route the EXACT (postflop) all-in call price from the canonical
    # snapshot. The snapshot's callable_amount (ledger-derived, capped at Hero's stack)
    # is authoritative for a call / call-off / call-vs-jam — a contaminated effective
    # stack must never turn a real ledger call (83526894 13.5, 84295102 2.3,
    # 83974506 16.8) into "unavailable".
    if _cakind in ('call_vs_jam', 'call_off') and _csnap:
        _snap_callable = _csnap.get('callable_amount_bb') or _csnap.get('to_call_bb')
        if _snap_callable:
            call_bb = round(_f(_snap_callable), 1)
            price_unavailable = False
            price_not_applicable = False
            price_source = 'canonical_action_ledger'
    return {
        'street': street,
        'decision_kind': kind,
        'hero_action_kind': _cakind,
        'hero_action_facing': facing or 'unknown',
        'hero_actual_action': hero_act,
        'call_amount_bb': round(call_bb, 1) if call_bb else None,
        'price_unavailable': price_unavailable,
        'price_not_applicable': price_not_applicable,
        'price_source': price_source,
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
        'dev_type': dtype,                         # 'Missed Open'/'Missed Rejam'/'Wide'
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
    # req: bounty certainty branches on the typed aggregate (REV4 B1):
    #   not_applicable -> no bounty adjustment exists, no uncertainty block
    #   unknown        -> block (missing-stack uncertainty)
    #   all/none/mixed -> collectibility known, use the canonical context (no block)
    # With no canonical context (hand absent) fall back to the pko-research flag.
    if bnt.get('is_pko'):
        _bagg = bnt.get('coverage_aggregate')
        if _bagg is None:
            if not bnt.get('collectibility_known'):
                return False, 'bounty_uncertain'
        elif _bagg == 'unknown':
            return False, 'bounty_uncertain'
    # req: known action node (price available + facing known) OR a rich,
    # ledger-built action line the analyst can read end-to-end.
    rich_line = bool(action_line and '|' in action_line)
    known_node = (not dn.get('price_unavailable')
                  and dn.get('hero_action_facing') != 'unknown')
    if not (known_node or rich_line):
        return False, 'unknown_node'
    # req: a real price engine must back the decision (never clear on no/unknown
    # price). 'not_applicable' is fine — a first-in jam has no call price but is
    # still backed by the push/fold class.
    if src_truth.get('price_engine') in ('none', 'unavailable'):
        return False, 'price_engine_unavailable'
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
    # safe chart label (GPT polish): never emit empty parens / dangling text.
    _lbl = (rng.get('display_label') if rng else '') or ''
    _lbl_txt = _lbl or 'your range chart'          # for "... for X" / "core X"
    _lbl_paren = (' (%s)' % _lbl) if _lbl else ''   # for "(X)" suffixes

    # --- policy 1: marginal opens are NOT errors -------------------------
    if rng and rng['is_marginal'] and rng['hero_hand_status'] in (
            'inside_extended', 'flagged'):
        grp = ('missed_%s_extended_open' % pos
               if 'open' in _lbl.lower()
               else 'marginal_preflop')
        return ('aggregate_only', 'Aggregate only', 'low', 'aggregate_only',
                ['bottom-of-range / extended hand'],
                f"{cards} is bottom-of-range{_lbl_paren}; "
                "confirm it is NOT graded an error.",
                f"Marginal open/defend{_lbl_paren} — bottom-5% "
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
        # GPT review #5: when the raw ledger all-in size differs from the
        # decision-effective stack, say BOTH so a 77BB jam is not read as a
        # 13BB decision (and the eff stack stays the reviewed basis).
        _asz, _ovj = dn.get('action_size_bb'), dn.get('overjam_bb')
        size_note = (f" [raw all-in {_asz:.0f}BB vs ~{eff:.0f}BB effective; "
                     f"overjam {_ovj:.0f}BB]" if (_ovj and _asz and eff) else "")
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
                    f"{call_bb:.1f}BB ({risked_pct:.0f}% stack)." + size_note,
                    grp, 72)
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
                    "jam/continue range — result is variance." + size_note,
                    grp, 24)
        # ordinary all-in: range equity decides; revealed result is luck. If
        # the auto_clear gate blocked on a specific ambiguity, name it.
        fm = ['range model confidence low']
        if ac_block and ac_block not in ('not_screened_clean', 'no_qualifying_basis'):
            fm.append('auto_clear blocked: ' + ac_block)
        return ('review_if_time', 'Review required', 'low', 'analyst_required',
                fm, rq,
                f"All-in {pos} {cards} at {eff:.0f}BB — verify range equity "
                "vs threshold (result was luck, not the basis)." + size_note,
                grp, 48)

    # --- Wide / Missed BB defend (chart-backed) --------------------------
    if rng and rng['hero_hand_status'] == 'outside_core':
        return ('review_if_time', 'Review required', 'medium',
                'analyst_required', ['pot odds / bounty may justify'],
                f"Is {cards} genuinely too wide for {_lbl_txt}, "
                "or do price/bounty/reads justify it?",
                f"Possible too-wide defend/open{_lbl_paren}.",
                'wide_%s' % pos, 40)
    if rng and rng['hero_hand_status'] == 'inside_core':
        dtype = rng.get('dev_type') or ''
        if 'Rejam' in dtype or 'Re-jam' in dtype:
            did = "called instead of re-jamming"
        elif 'Defend' in dtype:
            did = "folded instead of defending"
        elif 'Open' in dtype:
            did = "folded instead of opening"
        else:
            did = "passed up the spot"
        return ('must_review', 'Mistake', 'medium', 'analyst_required',
                ['ICM/satellite may excuse the decision'],
                f"{cards} is inside the core {_lbl_txt}; Hero "
                f"{did} preflop — confirm this is a real leak, not ICM-driven.",
                f"Missed core spot{_lbl_paren}.",
                'missed_core_%s' % pos, 60)

    # --- coolers: justified variance, low learning -----------------------
    if c.get('auto_verdict') == 'cooler_detected' or 'cooler' in (
            c.get('suggested_outcome') or ''):
        return ('aggregate_only', 'Cooler', 'medium', 'aggregate_only',
                [], "Confirm this is a structural cooler, not a leak.",
                "Cooler — both players committed strong; review only for "
                "closure.", 'cooler', 20)

    # --- v8.13.1 P1: loss-coverage screens (force-review, NOT auto-mistake) -
    # A hand that reached the worklist ONLY via a loss screen (biggest-loss or
    # postflop-loss) and was not classified above must still be cleared or
    # classified by the analyst — that is the 2026-06-13 gap (significant
    # losses absent from the worklist). It is a coverage rule, not a verdict.
    if c.get('screen_reason'):
        return ('must_review', 'Review required', 'medium', 'analyst_required',
                ['loss may be variance, not a leak'],
                f"{cards} {pos}: clear as variance or name the leak.",
                c.get('screen_reason'),
                'loss_screen', 58)

    # --- postflop / river calldowns + leftover candidates ----------------
    if c.get('went_to_sd') and not c.get('pf_allin') and _f(c.get('net_bb')) < -8:
        return ('review_if_time', 'Review required', 'low', 'analyst_required',
                ['villain may value-bet worse', 'blocker effects'],
                f"{(dn.get('street') or 'postflop').title()} decision with {cards}: "
                "does villain's line have enough bluffs to justify the call/bet?",
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
                           date_compact,
                           runtime=__import__(
                               'gem_version', fromlist=['RUNTIME_VERSION']
                           ).RUNTIME_VERSION):
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
        hand = hands_by_id.get(hid)
        # GPT review #2: the decision kind anchors node/line/stack to the
        # reviewed decision. A preflop deviation reads the PREFLOP street block,
        # never the hand's key_decision_street (which may be a later street).
        kind = _decision_kind(c, dev)
        _kds = 'preflop' if _is_preflop_kind(kind) else (
            (c.get('decision_math') or {}).get('key_decision_street', ''))
        dm_block = ((c.get('decision_math') or {}).get('streets') or {}).get(_kds, {})
        dn = _decision_node(c, kind, dev, hand)
        rng = _range_membership(c, dev, dev_charts)
        bnt = _bounty_context(c, pko)
        # v8.17.1 Iter-1 corrective: reconcile range label + bounty coverage to the
        # ONE canonical snapshot (FORMAT canonical values; never recompute). A
        # call-off must never carry a "re-jam over jam" range label (83915520), and
        # a known all-in confrontation must report typed coverage, not generic unknown.
        _akind_c = dn.get('hero_action_kind')
        if rng and _akind_c == 'call_vs_jam':
            _dt = rng.get('dev_type') or ''
            if 're-jam' in _dt.lower() or 'rejam' in _dt.lower():
                rng['dev_type'] = (_dt.replace('re-jam over jam', 'call vs jam')
                                   .replace('Re-jam', 'Call-vs-jam')
                                   .replace('re-jam', 'call vs jam')
                                   .replace('rejam', 'call vs jam'))
        if hand is not None and bnt.get('is_pko'):
            # REV4 B1: rebuild EVERY dependent bounty field from the ONE canonical
            # FUTURE-BLIND decision-time context — no stale field may survive from the
            # earlier _bounty_context() (the REV3 bug where collectibility_known and
            # adjustment_applied_to_decision contradicted not_applicable). Eligibility
            # (collectibility) and the stack-cover relationship are SEPARATE typed facts
            # (B3); collectibility_known means bounty eligibility known — NOT merely that
            # stack sizes compare.
            from gem_decision_snapshot import build_decision_bounty_context
            _bidx = _reviewed_action_index(hand, kind)
            _dbc = build_decision_bounty_context(hand, _bidx)
            _agg = _dbc['coverage_aggregate']
            # eligibility / collectibility
            bnt['coverage_aggregate'] = _agg
            bnt['coverage_reason'] = _dbc['coverage_reason']
            bnt['reason'] = _dbc['coverage_reason']            # back-compat alias
            bnt['coverage_mixed'] = _dbc['coverage_mixed']
            bnt['eligible_bounties_by_opponent'] = _dbc['eligible_bounties_by_opponent']
            bnt['bounty_eligibility_known'] = _dbc['bounty_eligibility_known']
            # back-compat: collectibility_known == bounty eligibility known (NOT cover)
            bnt['collectibility_known'] = _dbc['bounty_eligibility_known']
            bnt['hero_covers_relevant_villain'] = _dbc['hero_covers_relevant_villain']
            # stack-cover relationship — separate fact, never eligibility (B3)
            bnt['stack_cover_relationship_by_opponent'] = _dbc['stack_cover_relationship_by_opponent']
            bnt['cover_relationship_known'] = _dbc['cover_relationship_known']
            # adjustment: recomputed from the canonical context — true ONLY when a real
            # discount was applied to an ELIGIBLE, collectible bounty state (B1 invariant:
            # not_applicable/none/unknown => adjustment false).
            _discount = _f(c.get('bounty_discount_pp')) > 0
            _adj = bool(_discount and _agg in ('all', 'mixed')
                        and any(v == 'collectible' for v in
                                (_dbc['eligible_bounties_by_opponent'] or {}).values()))
            bnt['adjustment_applied_to_decision'] = _adj
            bnt['adjustment_source'] = 'pko_discount_on_eligible_bounty' if _adj else None
            # INVARIANT enforcement (defensive — must already hold from the context):
            if _agg == 'not_applicable':
                bnt['eligible_bounties_by_opponent'] = {}
                bnt['adjustment_applied_to_decision'] = False
                bnt['adjustment_source'] = None
                bnt['hero_covers_relevant_villain'] = None
        action_line = _canonical_action_line(c, hand, kind)
        src_truth = _source_truth(c, pko, dev)
        # v8.12.12 Obj-C: the decision node owns the price provenance. price_engine
        # is never 'none' when a price/sizing exists: not_applicable (no call
        # price), action_ledger / sidepot_reconciled / candidate_decision_math /
        # pot_odds_v8_12 (populated), or unavailable (needed but unsafe/missing).
        if dn.get('price_source'):
            src_truth['price_engine'] = dn['price_source']
        (bucket, proposal, conf, finality, fmodes, rq, why, grp,
         prio) = _classify(c, dn, rng, bnt, dm_block,
                           sources_by_id.get(hid, []), src_truth, action_line)
        # v8.12.11 (GPT-4/#5): surface the price failure mode wherever the
        # decision node could not produce a usable capped call amount. A
        # specific reason (e.g. side-pot/overjam reconciliation) wins over the
        # generic one.
        _pfr = dn.get('price_failure_reason') or (
            'decision price unavailable' if dn.get('price_unavailable') else None)
        if _pfr and _pfr not in fmodes:
            fmodes = fmodes + [_pfr]

        # v8.16.4 Obj 4: ADDITIVE actionable "why this hand" contract — enrich the
        # reason with street + Hero action + category and lint generic-only copy.
        # Never gate-drops a hand (dropping is a precision decision deferred to the
        # Analyst-Expansion measurement work); these are extra fields only.
        try:
            from gem_review_trust import build_why_review as _bwr
            _wr_srcs = sources_by_id.get(hid, [])
            if any(_s in ('mistakes', 'punts') for _s in _wr_srcs):
                _wr_cat = 'confirmed_mistake'
            elif bucket in ('must_review', 'review_if_time'):
                _wr_cat = 'candidate'
            else:
                _wr_cat = 'representative_leak'
            _why_contract = _bwr(
                dn.get('street'),
                dn.get('hero_actual_action') or dn.get('hero_action') or '',
                why, _wr_cat)
        except Exception:
            _why_contract = None

        po = pot_odds_by_hand.get(hid) or pot_odds_by_hand.get(_short(hid)) or {}
        items[hid] = {
            'hand_id': hid,
            'priority': prio,
            'bucket': bucket,
            'candidate_sources': sources_by_id.get(hid, []),
            'hero_cards': c.get('cards', ''),          # raw, suits preserved
            'hero_hand_label': _hand_label(c.get('cards')),  # chart notation
            'hero_pos': c.get('position', ''),
            'decision_kind': kind,                     # GPT review #2: explicit basis
            'effective_bb': dn['effective_bb_vs_relevant_villain'],
            'street': dn['street'],
            'spot_label': (pko.get('spot') or rng and rng['display_label']
                           or (c.get('action_summary', '')[:60]
                               if not _is_preflop_kind(kind) else '') or 'spot'),
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
            'why_contract': _why_contract,             # v8.16.4 Obj 4 (additive)
            'why_review_actionable': _why_contract is not None,
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
