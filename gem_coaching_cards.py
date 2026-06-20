"""GEM Coaching Cards — Phase 2 (programmatic, no LLM).

Three-layer architecture:
    decision_facts -> coaching_interpretation -> display_card

Renderer consumes only display_card.  This module performs NO rendering.
Phase 1: 7 primary template types.
Phase 2: blocker analysis + hero range awareness insight cards.
"""

from gem_parser import normalize_hand
import gem_decision_snapshot as _ds  # v8.17.1 Iter-1 canonical decision-time owner

_COACHING_VERSION = 'v2'

_ELIGIBLE_PHASES_ICM = {'bubble_zone', 'ft_zone'}

_PREMIUMS = {'AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo'}
_STRONG = {'TT', '99', 'AQs', 'AQo', 'AJs', 'KQs'}
_EP_POSITIONS = {'UTG', 'UTG+1', 'UTG+2', 'MP'}

_TEMPLATE_PRIORITY = [
    'satellite_caution',
    'icm_caution',
    'bounty_not_collectible',
    'bounty_ev',
    'multiway_caution',
    'call_math',
    'disciplined_fold',
]

# ── helpers ───────────────────────────────────────────────────────

def _g(d, *keys, default=None):
    """Nested safe-get."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def _clamp_words(text, limit):
    words = text.split()
    if len(words) <= limit:
        return text
    return ' '.join(words[:limit])


def _card_id(hand_id, street, card_type):
    return f"cc-{hand_id[-8:]}-{street}-{card_type}"


# ── eligibility ───────────────────────────────────────────────────

def _is_eligible(h, punt_ids, mistake_ids, eai_ids):
    """Return True if hand deserves a coaching card attempt."""
    hid = h.get('id', '')
    if hid in punt_ids or hid in mistake_ids:
        return True
    if hid in eai_ids:
        return True
    if h.get('pf_allin'):
        return True
    _fb_raw = h.get('facing_bets', 0)
    _fb_elig = len(_fb_raw) if isinstance(_fb_raw, (list, tuple)) else (_fb_raw or 0)
    if h.get('required_eq_pct') is not None and _fb_elig >= 1:
        return True
    fmt = h.get('format', '')
    phase = h.get('tournament_phase', '')
    if fmt == 'BOUNTY' and h.get('pf_allin'):
        return True
    if fmt == 'SATELLITE' and h.get('pf_allin'):
        return True
    if phase in _ELIGIBLE_PHASES_ICM and h.get('pf_allin'):
        return True
    return False


def _key_street(h):
    """Determine the primary decision street for this hand."""
    if h.get('pf_allin'):
        return 'preflop'
    ledger = h.get('action_ledger', [])
    hero_streets = set()
    for act in ledger:
        if act.get('player') == 'Hero' and act.get('action') not in ('fold', 'check', 'post'):
            hero_streets.add(act.get('street', 'preflop'))
    for st in ('river', 'turn', 'flop', 'preflop'):
        if st in hero_streets:
            return st
    return 'preflop'


# ── decision facts ────────────────────────────────────────────────

def _build_decision_facts(h, stats, report_data):
    """Build decision_facts for a single hand."""
    hid = h.get('id', '')
    street = _key_street(h)
    fmt = h.get('format', 'FREEZEOUT')
    phase = h.get('tournament_phase', '')

    n_players = h.get('n_players', 2)
    ledger = h.get('action_ledger', [])
    players_at_decision = set()
    for act in ledger:
        if act.get('street') == street and act.get('action') != 'fold':
            players_at_decision.add(act.get('player', ''))
    players_at_decision_count = max(len(players_at_decision), 2)

    hero_equity = h.get('eai_hero_equity')
    req_eq = h.get('required_eq_pct')
    pot_facing = h.get('pot_facing')
    call_amount = h.get('call_amount_bb')

    villain_stacks = {}
    for vpos, vdata in h.get('villains', {}).items():
        if isinstance(vdata, dict):
            villain_stacks[vpos] = vdata.get('stack_bb', 0)

    bounty_bb = h.get('bounty_value_bb', 0) if fmt == 'BOUNTY' else 0
    hero_stack = h.get('stack_bb', 0)
    # REV4 B2: decision-time bounty collectibility + cover are read from the ONE
    # canonical decision-time context (never the legacy realized scalar
    # h['bounty_collectible']). `hero_covers` means Hero covers an ELIGIBLE all-in
    # villain at the decision (not the all-seats stack compare, which wrongly counts
    # folded big stacks); `_collectibility` preserves mixed distinctly. The context is
    # stamped by the analyzer; build it on the fly if the analyzer hasn't run.
    # REV9 C2: the coaching card teaches the SELECTED decision, so its bounty context comes
    # from the REVIEWED action index (the worklist-authored ref in report_data, else the
    # analyzer/ledger-inferred ref) — NEVER the hand-level default (Hero's last action).
    _rdref_cc = ((report_data.get('reviewed_decision_ref_by_hand') or {}).get(hid)
                 or (report_data.get('reviewed_decision_ref_by_hand') or {}).get(
                     hid[-8:] if len(hid) > 8 else hid)
                 or h.get('reviewed_decision_ref') or {})
    _rev_idx_cc = _rdref_cc.get('hero_action_index')
    _dbc_cc = None
    if fmt == 'BOUNTY' or bounty_bb:
        try:
            if _rev_idx_cc is not None:
                _dbc_cc = _ds.build_decision_bounty_context(h, _rev_idx_cc)
            else:
                _dbc_cc = h.get('decision_bounty_context') or _ds.build_decision_bounty_context(h)
        except Exception:
            _dbc_cc = {}
    _dbc_cc = _dbc_cc or {}
    _cc_agg = _dbc_cc.get('coverage_aggregate') or _dbc_cc.get('aggregate')
    _collectibility = {'all': 'collectible', 'none': 'not_collectible', 'mixed': 'mixed',
                       'unknown': 'unknown', 'not_applicable': None}.get(_cc_agg)
    hero_covers = bool(_dbc_cc.get('hero_covers_relevant_villain'))

    range_facts = []
    for vpos, vdata in h.get('villains', {}).items():
        if isinstance(vdata, dict) and vdata.get('shown_cards'):
            range_facts.append({
                'villain': vpos,
                'range_text': vdata['shown_cards'],
                'confidence': 'high',
                'source': 'showdown',
            })

    vi = stats.get('villain_intel', {}) if isinstance(stats, dict) else {}
    evidence_count = 0
    if isinstance(vi, dict):
        atoms = vi.get('evidence_atoms', {})
        if isinstance(atoms, dict):
            evidence_count = sum(len(v) if isinstance(v, list) else 0
                                for v in atoms.values())

    auto_verdict = None
    auto_labels = report_data.get('auto_labels', {}) if isinstance(report_data, dict) else {}
    if isinstance(auto_labels, dict):
        auto_verdict = auto_labels.get(hid)

    eq_mode = 'numeric' if hero_equity is not None and players_at_decision_count <= 2 else 'suppressed'
    if hero_equity is not None and players_at_decision_count > 2:
        eq_mode = 'qualitative'

    pot_valid = 'passed'
    if pot_facing is not None and call_amount is not None:
        if pot_facing <= 0 or call_amount <= 0:
            pot_valid = 'failed'

    facts = {
        'hand_id': hid,
        'street': street,
        # REV9 C2: the selected reviewed action this card teaches (for the ownership inventory).
        'reviewed_action_index': _rev_idx_cc,
        'reviewed_selection_source': _rdref_cc.get('selection_source'),
        'bounty_context_owner': ('reviewed_action_index' if _rev_idx_cc is not None
                                 else ('hand_level_default' if (fmt == 'BOUNTY' or bounty_bb) else 'not_applicable')),
        'decision_meta': {
            'pf_action': h.get('pf_action', ''),
            'hero_bets': len(h.get('hero_bets', [])) if isinstance(h.get('hero_bets', []), (list, tuple)) else (h.get('hero_bets', 0) or 0),
            'facing_bets': len(h.get('facing_bets', [])) if isinstance(h.get('facing_bets', []), (list, tuple)) else (h.get('facing_bets', 0) or 0),
            'pf_allin': bool(h.get('pf_allin')),
            'auto_verdict': auto_verdict,
            'hero_action': h.get('pf_action', '') if street == 'preflop' else '',
        },
        'game_context': {
            'format': fmt,
            'game_type': h.get('game_type', ''),
            'table_size': h.get('table_size', 0),
            'n_players': n_players,
            'players_at_decision': players_at_decision_count,
        },
        'hero': {
            'position': h.get('position', ''),
            'cards': h.get('cards', []),
            'stack_bb': hero_stack,
            'eff_stack_bb': h.get('eff_stack_bb', 0),
        },
        'villains': {
            'stacks': villain_stacks,
            'archetype': h.get('villain_archetype', ''),
            'archetype_label': h.get('villain_archetype_label', ''),
        },
        'board': {
            'cards': h.get('board', []),
            'texture': h.get('board_texture', ''),
        },
        'pot_facts': {
            'pot_facing': pot_facing,
            'call_amount_bb': call_amount,
            'pot_validation': pot_valid,
        },
        'math_facts': {
            'required_eq_pct': req_eq,
            'hero_equity': hero_equity,
            'equity_display_mode': eq_mode,
        },
        'range_facts': range_facts,
        'bounty_facts': {
            'bounty_value_bb': bounty_bb,
            'is_bounty': fmt == 'BOUNTY',
            'hero_covers': hero_covers,
            'collectibility': _collectibility,
            'bounty_confidence': 'medium' if h.get('bounty_type') == 'mystery' else 'high',
        },
        'icm_context': {
            'tournament_phase': phase,
            'is_bubble': phase == 'bubble_zone',
            'is_final_table': phase == 'ft_zone',
            'suppress_confident_chip_ev_verdict': phase in _ELIGIBLE_PHASES_ICM,
        },
        'satellite_context': {
            'is_satellite': fmt == 'SATELLITE',
            'suppress_chip_ev_allin_verdict': fmt == 'SATELLITE',
        },
        'villain_reads': {
            'evidence_count': evidence_count,
            'available_before_decision': True,
        },
        'blocker_facts': {'enabled': False},
        'hero_range_facts': {'enabled': False},
        'candidate_alternatives': [],
        'provenance': {
            'facts_generated_by': 'programmatic',
            'facts_version': _COACHING_VERSION,
        },
    }

    alts = []
    hero_act = facts['decision_meta']['pf_action']
    if hero_act in ('call', 'fold'):
        alts = [
            {'action': 'call', 'ranking_confidence': 'medium' if req_eq else 'low'},
            {'action': 'fold', 'ranking_confidence': 'medium' if req_eq else 'low'},
        ]
        if h.get('pf_allin'):
            alts.append({'action': 'raise', 'ranking_confidence': 'low'})
    facts['candidate_alternatives'] = alts

    facts['_hand'] = h  # v8.12.1: templates may read enrichments (pko_context)
    return facts


# ── Phase 2 enrichment ───────────────────────────────────────────

def _compute_blocker_facts(facts):
    """Compute blocker analysis from hero cards + board.  Mutates facts in place."""
    hero_cards = facts.get('hero', {}).get('cards', [])
    # v8.17.1 Iteration 1 (temporal board): blocker analysis must use the board Hero
    # ACTUALLY saw at the decision street, never the final runout. A preflop all-in
    # saw no board -> board_at_decision == [] -> no blocker card. This killed 11
    # "your A blocks the nut flush on this 3-flush board" cards stamped on preflop
    # jams that merely ran out to a flush. Flop-decision blocker cards keep their
    # 3-card flop board and still fire.
    board_cards = _ds.board_at_decision(facts.get('board', {}).get('cards', []),
                                        facts.get('street', 'preflop'))

    if len(hero_cards) < 2 or len(board_cards) < 3:
        return

    board_suit_counts = {}
    for c in board_cards:
        s = c[1] if len(c) >= 2 else ''
        if s:
            board_suit_counts[s] = board_suit_counts.get(s, 0) + 1

    flush_suit = None
    flush_count = 0
    for s in sorted(board_suit_counts):
        if board_suit_counts[s] >= 3 and board_suit_counts[s] > flush_count:
            flush_suit = s
            flush_count = board_suit_counts[s]

    hero_flush_rank = None
    hero_suit_count = 0
    if flush_suit:
        for hc in hero_cards:
            if len(hc) >= 2 and hc[1] == flush_suit:
                hero_suit_count += 1
                r = hc[0]
                if hero_flush_rank is None or _rank_val(r) > _rank_val(hero_flush_rank):
                    hero_flush_rank = r

    hero_has_made_flush = (hero_suit_count + flush_count) >= 5 if flush_suit else False
    has_ace_of_flush = hero_flush_rank == 'A' if flush_suit else False

    nut_flush_made = has_ace_of_flush and hero_has_made_flush
    nut_flush_blocker = has_ace_of_flush and not hero_has_made_flush
    strong_flush_blocker = (hero_flush_rank in ('K', 'Q') and not has_ace_of_flush
                            and not hero_has_made_flush) if flush_suit else False
    no_flush_blocker = (flush_suit is not None and hero_suit_count == 0)

    board_ranks = [c[0] for c in board_cards if len(c) >= 2]
    rank_counts = {}
    for r in board_ranks:
        rank_counts[r] = rank_counts.get(r, 0) + 1
    paired_ranks = [r for r, cnt in rank_counts.items() if cnt >= 2]

    paired_board_blocker = False
    paired_board_blocker_rank = None
    for pr in paired_ranks:
        for hc in hero_cards:
            if len(hc) >= 2 and hc[0] == pr:
                paired_board_blocker = True
                paired_board_blocker_rank = pr
                break
        if paired_board_blocker:
            break

    enabled = (nut_flush_blocker or nut_flush_made or no_flush_blocker
               or paired_board_blocker)

    facts['blocker_facts'] = {
        'enabled': enabled,
        'board_flush_suit': flush_suit,
        'flush_card_count': flush_count,
        'hero_flush_suit_rank': hero_flush_rank,
        'hero_has_made_flush': hero_has_made_flush,
        'nut_flush_blocker': nut_flush_blocker,
        'nut_flush_made_hand': nut_flush_made,
        'strong_flush_blocker': strong_flush_blocker,
        'no_flush_blocker': no_flush_blocker,
        'paired_board_blocker': paired_board_blocker,
        'paired_board_blocker_rank': paired_board_blocker_rank,
    }


_RANK_VAL_MAP = {r: i for i, r in enumerate('23456789TJQKA')}

def _rank_val(r):
    return _RANK_VAL_MAP.get(r, 0)


def _depth_tier(stack_bb):
    if stack_bb < 12:
        return None
    if stack_bb < 20:
        return 'OPEN_10-20BB'
    if stack_bb < 40:
        return 'OPEN_20-40BB'
    return 'OPEN_100BB'


def _compute_hero_range_facts(facts, ranges):
    """Compute hero perceived range position.  Mutates facts in place."""
    if not ranges:
        return

    hero = facts.get('hero', {})
    hero_cards = hero.get('cards', [])
    position = hero.get('position', '')
    stack_bb = hero.get('stack_bb', 0)

    if len(hero_cards) < 2 or not position:
        return

    hand_class = normalize_hand(hero_cards)
    if not hand_class:
        return

    tier = _depth_tier(stack_bb)
    if tier is None:
        return

    if position == 'SB' and tier == 'OPEN_100BB':
        chart_name = 'OPEN_100BB_SB_RAISE'
    else:
        chart_name = f'{tier}_{position}'

    chart = ranges.get(chart_name, set())
    if not chart:
        return

    in_range = hand_class in chart
    if hand_class in _PREMIUMS:
        range_position = 'premium'
    elif hand_class in _STRONG:
        range_position = 'strong'
    elif in_range:
        range_position = 'standard'
    else:
        range_position = 'outside'

    dm = facts.get('decision_meta', {})
    pf_action = dm.get('pf_action', '')
    facing_bets = dm.get('facing_bets', 0)
    sc = facts.get('satellite_context', {})
    ic = facts.get('icm_context', {})

    if pf_action == 'raise' and facing_bets == 0:
        range_context = 'open'
    elif pf_action == 'call' and position == 'BB':
        range_context = 'bb_defend'
    elif pf_action == 'call' and facing_bets >= 1 and position != 'BB':
        range_context = 'flat_vs_open'
    elif pf_action == 'call' and position != 'BB':
        range_context = 'cold_call'
    else:
        range_context = 'unknown'

    is_capped = (range_context in ('flat_vs_open', 'cold_call')
                 and range_position in ('premium', 'strong')
                 and stack_bb >= 20
                 and not sc.get('is_satellite')
                 and not ic.get('suppress_confident_chip_ev_verdict'))

    facts['hero_range_facts'] = {
        'enabled': True,
        'hand_class': hand_class,
        'chart_name': chart_name,
        'in_range': in_range,
        'range_position': range_position,
        'range_context': range_context,
        'is_capped': is_capped,
        'chart_size': len(chart),
    }


# ── quality gates ─────────────────────────────────────────────────

def derive_quality_gates(facts):
    """Compute quality gates from decision_facts.
    Returns (gates_dict, display_confidence, suppress_reason).
    """
    mf = facts.get('math_facts', {})
    pf = facts.get('pot_facts', {})
    bf = facts.get('bounty_facts', {})
    gc = facts.get('game_context', {})
    vr = facts.get('villain_reads', {})
    ic = facts.get('icm_context', {})
    sc = facts.get('satellite_context', {})
    rf = facts.get('range_facts', [])
    ca = facts.get('candidate_alternatives', [])

    gates = {
        'numeric_equity_allowed': (
            mf.get('equity_display_mode') == 'numeric'
            and len(rf) > 0
            and pf.get('pot_validation') == 'passed'
        ),
        'range_required_and_present': len(rf) > 0,
        'multiway_equity_safe': gc.get('players_at_decision', 2) <= 2,
        'pot_validation_passed': pf.get('pot_validation') == 'passed',
        'bounty_math_safe': (
            bf.get('bounty_confidence', 'high') != 'missing'
            if bf.get('is_bounty') else True
        ),
        'villain_read_safe': vr.get('evidence_count', 0) >= 1,
        'icm_allows_confident_verdict': not ic.get('suppress_confident_chip_ev_verdict', False),
        'satellite_allows_chip_ev_verdict': not sc.get('suppress_chip_ev_allin_verdict', False),
        'blocker_commentary_allowed': facts.get('blocker_facts', {}).get('enabled', False),
        'hero_range_commentary_allowed': facts.get('hero_range_facts', {}).get('enabled', False),
        'action_ranking_supported': (
            sum(1 for a in ca if a.get('ranking_confidence', 'low') in ('medium', 'high')) >= 2
        ),
    }

    weakest = 'high'
    if not gates['pot_validation_passed']:
        weakest = 'low'
    elif not gates['multiway_equity_safe']:
        weakest = 'medium'
    elif not gates['range_required_and_present']:
        weakest = 'medium'
    elif mf.get('equity_display_mode') == 'suppressed':
        weakest = 'medium'

    suppress = None
    if not gates['pot_validation_passed'] and not bf.get('is_bounty'):
        suppress = 'pot_validation_failed'

    return gates, weakest, suppress


# ── template interpretation ───────────────────────────────────────

def _tmpl_call_math(facts, gates):
    """HU call/fold with numeric equity."""
    mf = facts['math_facts']
    hero_eq = mf.get('hero_equity')
    req_eq = mf.get('required_eq_pct')
    if hero_eq is None or req_eq is None:
        return None
    if not gates.get('numeric_equity_allowed'):
        return None
    if not gates.get('multiway_equity_safe'):
        return None

    call_ok = hero_eq >= req_eq
    margin = abs(hero_eq - req_eq)
    close = margin < 5

    if call_ok:
        verdict = 'Call is profitable by price' if close else 'Clear call'
        if gates.get('action_ranking_supported') and not close:
            verdict = 'Call. Do not raise.'
    else:
        verdict = 'Close fold' if close else 'Clear fold'

    headline = f"{'Call' if call_ok else 'Fold'} — {hero_eq:.0f}% vs {req_eq:.0f}% needed"

    why = f"Your equity ({hero_eq:.0f}%) {'exceeds' if call_ok else 'falls short of'} the {req_eq:.0f}% needed to break even."

    learn = "Pot odds define the minimum equity you need to call profitably."
    if close:
        learn = "Close spots near breakeven are often decided by position and implied odds."

    plan = "Compare your equity estimate to pot odds before every big call."

    metrics = [
        {'label': 'Your equity', 'value': f'{hero_eq:.0f}%', 'variant': ''},
        {'label': 'Need', 'value': f'{req_eq:.0f}%', 'variant': ''},
    ]
    pf = facts.get('pot_facts', {})
    if pf.get('pot_facing') and pf.get('call_amount_bb'):
        odds = pf['pot_facing'] / pf['call_amount_bb'] if pf['call_amount_bb'] > 0 else 0
        metrics.append({'label': 'Pot odds', 'value': f'{odds:.1f}:1', 'variant': 'money'})

    return {
        'card_type': 'call_math',
        'poker_verdict': verdict,
        'headline': _clamp_words(headline, 9),
        'why': _clamp_words(why, 22),
        'learn': _clamp_words(learn, 24),
        'plan': _clamp_words(plan, 18),
        'metrics': metrics[:4],
        'ranges': facts.get('range_facts', [])[:2],
        'warnings': [],
        'variant': 'good' if call_ok else 'warn',
    }


def _tmpl_bounty_ev(facts, gates):
    """Bounty-adjusted call threshold."""
    bf = facts['bounty_facts']
    if not bf.get('is_bounty') or not bf.get('hero_covers'):
        return None
    mf = facts['math_facts']
    req_eq = mf.get('required_eq_pct')
    hero_eq = mf.get('hero_equity')
    if req_eq is None:
        return None
    bounty_bb = bf.get('bounty_value_bb', 0)
    if bounty_bb <= 0:
        return None

    pf = facts.get('pot_facts', {})
    pot = pf.get('pot_facing', 0)
    call_amt = pf.get('call_amount_bb', 0)
    adj_pot = pot + bounty_bb
    adj_req = (call_amt / (adj_pot + call_amt) * 100) if (adj_pot + call_amt) > 0 else req_eq

    bounty_only = False
    if hero_eq is not None:
        bounty_only = hero_eq < req_eq and hero_eq >= adj_req

    headline = "Bounty shifts the call threshold"
    if bounty_only:
        headline = "Call only because bounty is worth enough"

    verdict = 'Bounty call' if bounty_only else 'Bounty-adjusted call'
    why = f"Without bounty you need {req_eq:.0f}%. With {bounty_bb:.0f}BB bounty the threshold drops to {adj_req:.0f}%."

    learn = "Bounty value adds to the pot, lowering the equity you need to call."
    plan = "Factor bounty into pot odds for every covered villain."

    metrics = [
        {'label': 'Without bounty', 'value': f'{req_eq:.0f}%', 'variant': ''},
        {'label': 'With bounty', 'value': f'{adj_req:.0f}%', 'variant': 'money'},
        {'label': 'Bounty', 'value': f'{bounty_bb:.0f}BB', 'variant': 'money'},
    ]
    if hero_eq is not None:
        metrics.insert(0, {'label': 'Your equity', 'value': f'{hero_eq:.0f}%', 'variant': ''})

    return {
        'card_type': 'bounty_ev',
        'poker_verdict': verdict,
        'headline': _clamp_words(headline, 9),
        'why': _clamp_words(why, 22),
        'learn': _clamp_words(learn, 24),
        'plan': _clamp_words(plan, 18),
        'metrics': metrics[:4],
        'ranges': facts.get('range_facts', [])[:2],
        'warnings': [],
        'variant': 'good' if bounty_only else 'blue',
    }


def _tmpl_bounty_not_collectible(facts, gates):
    """Hero doesn't cover villain — bounty not collectible."""
    bf = facts['bounty_facts']
    if not bf.get('is_bounty'):
        return None
    # v8.14.1 rev-3 (Blocker 2): gate on the canonical collectibility (shared with
    # the analyzer's "bounty covers villain" flag) so this card can never fire on
    # the same hand that says the bounty is collectible. Only fire when the cover
    # math is KNOWN not-collectible — never on 'unknown' or 'collectible'.
    if bf.get('collectibility') != 'not_collectible':
        return None
    if not facts['decision_meta'].get('pf_allin'):
        return None

    headline = "Bounty is not collectible here"
    verdict = 'Play for chip EV only'
    why = "You do not cover this villain. Winning this all-in does not collect the bounty."
    learn = "Bounty only pays when you eliminate the opponent by covering their stack."
    plan = "Treat non-covered opponents as standard chip-EV decisions."

    return {
        'card_type': 'bounty_not_collectible',
        'poker_verdict': verdict,
        'headline': _clamp_words(headline, 9),
        'why': _clamp_words(why, 22),
        'learn': _clamp_words(learn, 24),
        'plan': _clamp_words(plan, 18),
        'metrics': [],
        'ranges': [],
        'warnings': [],
        'variant': 'warn',
    }


def _tmpl_multiway_caution(facts, gates):
    """Multiway pot — equity display suppressed.

    v8.12.3 (Ron QA, hand 61459519): players_at_decision counted DEALT
    players, so an 11BB first-in open-jam read '8-way pot — equity is less
    reliable', which is meaningless. The card now (a) never fires on
    first-in all-in jams, and (b) requires 3+ players to have actually
    entered the pot (VPIP'd), falling back to players_at_flop."""
    h = facts.get('_hand') or {}
    if h.get('pf_allin') and h.get('first_in'):
        return None
    # v8.17.1 Iteration 1 (actual pot entrants): count players actually CONTESTING
    # the pot at Hero's decision (committed, not folded, dead-short side pots
    # excluded) — NOT everyone dealt. players_at_flop was 0 for a preflop-ending jam
    # so the old code fell back to players_at_decision, which counted blind posters
    # => "8-way pot — equity less reliable" on a jam that folded out (83506399), and
    # a 0.8BB dead-short all-in inflated 84990829 to "3-way". The canonical snapshot
    # owns the contesting count.
    n = _ds.contesting_count(h)
    if n <= 2:
        return None

    headline = f"{n}-way pot — equity is less reliable"
    verdict = 'Multiway caution'
    why = f"With {n} players in the pot, HU equity estimates do not apply. Positional and hand-reading edges matter more."
    learn = "Multiway pots reward tighter ranges and stronger draws."
    plan = "Focus on hand strength and position rather than raw equity math."

    return {
        'card_type': 'multiway_caution',
        'poker_verdict': verdict,
        'headline': _clamp_words(headline, 9),
        'why': _clamp_words(why, 22),
        'learn': _clamp_words(learn, 24),
        'plan': _clamp_words(plan, 18),
        'metrics': [],
        'ranges': [],
        'warnings': [],
        'variant': 'warn',
    }


def _tmpl_icm_caution(facts, gates):
    """ICM pressure — chip-EV suppressed."""
    ic = facts['icm_context']
    if not ic.get('suppress_confident_chip_ev_verdict'):
        return None
    if facts['satellite_context'].get('suppress_chip_ev_allin_verdict'):
        return None

    phase_label = 'bubble' if ic.get('is_bubble') else 'final table'
    headline = f"ICM pressure — {phase_label} zone"
    verdict = 'ICM caution'
    why = f"Near the {phase_label}, chip-EV alone does not capture pay-jump risk. Tighter ranges are standard."
    learn = "ICM means chips won are worth less than chips lost near pay jumps."
    plan = "Tighten calling ranges and avoid marginal all-ins near the bubble."

    return {
        'card_type': 'icm_caution',
        'poker_verdict': verdict,
        'headline': _clamp_words(headline, 9),
        'why': _clamp_words(why, 22),
        'learn': _clamp_words(learn, 24),
        'plan': _clamp_words(plan, 18),
        'metrics': [],
        'ranges': [],
        'warnings': [],
        'variant': 'warn',
    }


def _tmpl_satellite_caution(facts, gates):
    """Satellite format — chip accumulation is not the goal."""
    sc = facts['satellite_context']
    if not sc.get('suppress_chip_ev_allin_verdict'):
        return None

    headline = "Satellite — survive, do not accumulate"
    verdict = 'Satellite caution'
    why = "In a satellite, finishing in the seats is all that matters. Extra chips above the seat threshold have zero value."
    learn = "Satellite strategy inverts normal MTT logic: fold equity is survival equity."
    plan = "Avoid unnecessary all-ins. Chip-EV math does not apply to seat races."

    return {
        'card_type': 'satellite_caution',
        'poker_verdict': verdict,
        'headline': _clamp_words(headline, 9),
        'why': _clamp_words(why, 22),
        'learn': _clamp_words(learn, 24),
        'plan': _clamp_words(plan, 18),
        'metrics': [],
        'ranges': [],
        'warnings': [],
        'variant': 'bad',
    }


def _tmpl_disciplined_fold(facts, gates):
    """Close fold justified by context."""
    dm = facts['decision_meta']
    if dm.get('pf_action') != 'fold':
        return None
    mf = facts['math_facts']
    req_eq = mf.get('required_eq_pct')
    if req_eq is None:
        return None

    headline = "Disciplined fold at close price"
    verdict = 'Good fold'
    why = "The pot odds were close but context factors (position, ICM, villain tendencies) favor folding."
    learn = "Close folds often save more EV than marginal calls gain."
    plan = "When the math is close, let table dynamics and ICM break the tie."

    metrics = [{'label': 'Needed', 'value': f'{req_eq:.0f}%', 'variant': ''}]

    return {
        'card_type': 'disciplined_fold',
        'poker_verdict': verdict,
        'headline': _clamp_words(headline, 9),
        'why': _clamp_words(why, 22),
        'learn': _clamp_words(learn, 24),
        'plan': _clamp_words(plan, 18),
        'metrics': metrics,
        'ranges': [],
        'warnings': [],
        'variant': 'good',
    }


_TEMPLATES = [
    ('satellite_caution', _tmpl_satellite_caution),
    ('icm_caution', _tmpl_icm_caution),
    ('bounty_not_collectible', _tmpl_bounty_not_collectible),
    ('bounty_ev', _tmpl_bounty_ev),
    ('multiway_caution', _tmpl_multiway_caution),
    ('call_math', _tmpl_call_math),
    ('disciplined_fold', _tmpl_disciplined_fold),
]


def _select_template(facts, gates):
    """Run templates in priority order; return first match or None."""
    for _name, fn in _TEMPLATES:
        result = fn(facts, gates)
        if result is not None:
            return result
    return None


# ── Phase 2 insight templates ────────────────────────────────────

_SUIT_SYMBOL = {'h': '♥', 'd': '♦', 'c': '♣', 's': '♠'}

def _tmpl_blocker_insight(facts, gates):
    """Phase 2: blocker awareness teaching card."""
    if not gates.get('blocker_commentary_allowed'):
        return None
    bf = facts.get('blocker_facts', {})
    if not bf.get('enabled'):
        return None

    suit = bf.get('board_flush_suit', '')
    suit_sym = _SUIT_SYMBOL.get(suit, suit)
    flush_ct = bf.get('flush_card_count', 0)

    if bf.get('nut_flush_made_hand'):
        headline = "You have the nut flush"
        verdict = "Nut flush made"
        why = f"Your A{suit_sym} completes the nut flush on this {flush_ct}-suited board."
        learn = "When you hold the nut flush you have the board locked and can value bet confidently."
        plan = "With the nuts, focus on maximizing value through sizing."
        return {
            'card_type': 'blocker_insight', '_insight_trigger': 'nut_flush_made',
            'poker_verdict': verdict,
            'headline': _clamp_words(headline, 9),
            'why': _clamp_words(why, 22),
            'learn': _clamp_words(learn, 24),
            'plan': _clamp_words(plan, 18),
            'metrics': [], 'ranges': [], 'warnings': [],
            'variant': 'blue',
        }

    if bf.get('nut_flush_blocker'):
        headline = f"Your A{suit_sym} blocks the nut flush"
        verdict = "Blocker advantage"
        why = f"Holding A{suit_sym} means villain cannot have the nut flush on this {flush_ct}-suited board."
        learn = "The nut flush blocker removes villain's strongest flush combos from their range."
        plan = "Use nut blocker hands as prime bluff-catch candidates."
        return {
            'card_type': 'blocker_insight', '_insight_trigger': 'nut_flush_blocker',
            'poker_verdict': verdict,
            'headline': _clamp_words(headline, 9),
            'why': _clamp_words(why, 22),
            'learn': _clamp_words(learn, 24),
            'plan': _clamp_words(plan, 18),
            'metrics': [], 'ranges': [], 'warnings': [],
            'variant': 'blue',
        }

    if bf.get('no_flush_blocker'):
        dm = facts.get('decision_meta', {})
        fb = dm.get('facing_bets', 0)
        fb = len(fb) if isinstance(fb, (list, tuple)) else (fb or 0)
        hb = dm.get('hero_bets', 0)
        hb = len(hb) if isinstance(hb, (list, tuple)) else (hb or 0)
        if fb < 1 and hb < 1 and not dm.get('pf_allin'):
            return None
        headline = "No flush blocker on wet board"
        verdict = "Missing blocker"
        why = f"You hold no {suit_sym} cards on a {flush_ct}-flush board so villain's flush combos are at full strength."
        learn = "Without a flush blocker you must give more weight to villain having completed the flush."
        plan = "Without blockers, lean toward folding marginal hands on flush boards."
        return {
            'card_type': 'blocker_insight', '_insight_trigger': 'no_flush_blocker',
            'poker_verdict': verdict,
            'headline': _clamp_words(headline, 9),
            'why': _clamp_words(why, 22),
            'learn': _clamp_words(learn, 24),
            'plan': _clamp_words(plan, 18),
            'metrics': [], 'ranges': [], 'warnings': [],
            'variant': 'blue',
        }

    if bf.get('paired_board_blocker'):
        rank = bf.get('paired_board_blocker_rank', '?')
        headline = "You block trips and full houses"
        verdict = "Paired-board blocker"
        why = f"Holding a {rank} on a paired board blocks villain from having trips or a full house with that rank."
        learn = "Blocking trips and full houses reduces villain's strong value combos on paired boards."
        plan = "Paired-board blockers favor lighter call-downs when villain represents big hands."
        return {
            'card_type': 'blocker_insight', '_insight_trigger': 'paired_board_blocker',
            'poker_verdict': verdict,
            'headline': _clamp_words(headline, 9),
            'why': _clamp_words(why, 22),
            'learn': _clamp_words(learn, 24),
            'plan': _clamp_words(plan, 18),
            'metrics': [], 'ranges': [], 'warnings': [],
            'variant': 'blue',
        }

    return None


def _tmpl_range_awareness(facts, gates):
    """Phase 2: hero perceived range teaching card."""
    if not gates.get('hero_range_commentary_allowed'):
        return None
    hrf = facts.get('hero_range_facts', {})
    if not hrf.get('enabled'):
        return None

    rp = hrf.get('range_position', '')
    rc = hrf.get('range_context', '')
    hc = hrf.get('hand_class', '')
    cn = hrf.get('chart_name', '')
    pos = facts.get('hero', {}).get('position', '')

    if rp == 'outside' and rc == 'open':
        headline = "This hand is outside your chart"
        verdict = "Range deviation"
        why = f"A standard {cn} range does not include {hc}. This is a deviation from your opening chart."
        learn = "Playing outside your range can be exploitative but makes your range harder to construct."
        plan = "Note whether deviations are deliberate exploits or leaks."
        return {
            'card_type': 'range_awareness', '_insight_trigger': 'outside_chart',
            'poker_verdict': verdict,
            'headline': _clamp_words(headline, 9),
            'why': _clamp_words(why, 22),
            'learn': _clamp_words(learn, 24),
            'plan': _clamp_words(plan, 18),
            'metrics': [], 'ranges': [], 'warnings': [],
            'variant': 'blue',
        }

    if hrf.get('is_capped') and rc in ('flat_vs_open', 'cold_call'):
        headline = "Flat-calling caps your perceived range"
        verdict = "Capped range signal"
        why = f"By flat-calling with {hc}, villain reads your range as capped with no premiums expected."
        learn = "Flat-callers are perceived as capped so villain may over-bet expecting medium-strength holdings."
        plan = "After flatting a premium, be ready for aggressive villain lines."
        return {
            'card_type': 'range_awareness', '_insight_trigger': 'capped_premium',
            'poker_verdict': verdict,
            'headline': _clamp_words(headline, 9),
            'why': _clamp_words(why, 22),
            'learn': _clamp_words(learn, 24),
            'plan': _clamp_words(plan, 18),
            'metrics': [], 'ranges': [], 'warnings': [],
            'variant': 'blue',
        }

    if rp == 'premium' and pos in _EP_POSITIONS and rc == 'open':
        headline = "Premium from EP signals strength"
        verdict = "Strong range perception"
        why = f"Opening {hc} from {pos} tells villain your range is tight and strong."
        learn = "Early-position opens carry a tight-range reputation so villain folds more or 3-bets only strong."
        plan = "From EP with premiums, expect folds or strong resistance."
        return {
            'card_type': 'range_awareness', '_insight_trigger': 'premium_early',
            'poker_verdict': verdict,
            'headline': _clamp_words(headline, 9),
            'why': _clamp_words(why, 22),
            'learn': _clamp_words(learn, 24),
            'plan': _clamp_words(plan, 18),
            'metrics': [], 'ranges': [], 'warnings': [],
            'variant': 'blue',
        }

    return None


def _tmpl_pko_pressure(facts, gates):
    """v8.12.1: PKO pressure insight (Review language ONLY).

    Ship conditions (review-mandated): title contains 'Review'; never in
    Top Punts / confirmed-leak counts (insight cards never are); distinct
    blue variant; per-report cap; requires pko_context.enabled + recorded
    confidence + classification in {Missed, Review}; Missed additionally
    requires the Classic chart backstop."""
    h = facts.get('_hand') or {}
    ctx = h.get('pko_context') or {}
    if not ctx.get('enabled'):
        return None
    cls = ctx.get('classification')
    if cls not in ('Missed', 'Review'):
        return None
    if cls == 'Missed' and ctx.get('classic_support_source') != 'chart':
        return None
    if not ctx.get('confidence'):
        return None
    cap = getattr(_tmpl_pko_pressure, '_count', 0)
    if cap >= 6:
        return None
    _tmpl_pko_pressure._count = cap + 1
    rng = ctx.get('delta_range_pp') or [0, 0]
    rng_txt = ('%+.1f to %+.1fpp' % (rng[0], rng[1])
               if rng[0] != rng[1] else '%+.1fpp' % rng[0])
    return {
        'card_type': 'pko_pressure',
        '_insight_trigger': 'pko_' + cls.lower(),
        # v8.17.1 Iter-1: PKO bounty pressure is a PREFLOP defend/jam decision; pin
        # the street so the card never renders on a later (flop/river) action street.
        'street': 'preflop',
        'poker_verdict': 'review',
        'metrics': [], 'ranges': [], 'warnings': [],
        'variant': 'blue',
        'headline': 'PKO Review: bounty pressure spot',
        'why': ('GTOW PKO aggregates widen this defend family by '
                + rng_txt + ' vs Classic — ' + str(ctx.get('spot', ''))
                + ' at ' + str(ctx.get('depth_bucket', '')) + '.'),
        'learn': ('Bounty pressure is situational: shortness and multiway '
                  'amplify it; covered heads-up spots barely move.'),
        'plan': ('High-priority review spot, not an automatic mistake — '
                 'drill this family in the PKO teaching table (S4.2).'),
    }


_INSIGHT_TEMPLATES = [
    ('pko_pressure', _tmpl_pko_pressure),
    ('blocker_insight', _tmpl_blocker_insight),
    ('range_awareness', _tmpl_range_awareness),
]


def _select_insight(facts, gates):
    """Run insight templates in priority order; return first match or None."""
    for _name, fn in _INSIGHT_TEMPLATES:
        result = fn(facts, gates)
        if result is not None:
            return result
    return None


# ── semantic assertions ───────────────────────────────────────────

def _run_assertions(facts, gates, interp):
    """Run semantic assertions.  Returns (ok, reasons_list)."""
    reasons = []

    # A: No equity without range
    if interp.get('card_type') == 'call_math' and not gates.get('range_required_and_present'):
        reasons.append('A: numeric equity card has no range')

    # B: Call/fold threshold consistency
    if interp.get('card_type') == 'call_math':
        mf = facts['math_facts']
        hero_eq = mf.get('hero_equity', 0)
        req_eq = mf.get('required_eq_pct', 0)
        verdict = interp.get('poker_verdict', '')
        if 'Call' in verdict and hero_eq < req_eq - 5:
            reasons.append('B: call verdict with equity well below threshold')
        if 'Fold' in verdict and hero_eq > req_eq + 5:
            reasons.append('B: fold verdict with equity well above threshold')

    # C: Action ranking guard
    if 'Do not raise' in interp.get('poker_verdict', ''):
        if not gates.get('action_ranking_supported'):
            reasons.append('C: hard action ranking without alternatives')

    # D: Bounty coverage
    if interp.get('card_type') == 'bounty_ev':
        bf = facts['bounty_facts']
        if not bf.get('hero_covers'):
            reasons.append('D: bounty EV card but hero does not cover')

    # H: Satellite > ICM priority
    sc = facts.get('satellite_context', {})
    ic = facts.get('icm_context', {})
    if sc.get('is_satellite') and interp.get('card_type') == 'icm_caution':
        reasons.append('H: satellite should take priority over ICM')

    # I: Villain exploit timing
    vr = facts.get('villain_reads', {})
    if 'exploit' in interp.get('card_type', ''):
        if not vr.get('available_before_decision'):
            reasons.append('I: villain read not available before decision')

    # K: Sizing without hero range
    if 'sizing' in interp.get('card_type', ''):
        if not facts.get('hero_range_facts', {}).get('enabled'):
            reasons.append('K: sizing card without hero range')

    # L: Claim reconciliation
    dm = facts.get('decision_meta', {})
    auto_v = dm.get('auto_verdict')
    if auto_v and 'chart_standard' in str(auto_v):
        verdict = interp.get('poker_verdict', '')
        if 'fold' in verdict.lower() or 'mistake' in verdict.lower():
            reasons.append('L: contradicts chart-standard auto-verdict')

    ct = interp.get('card_type', '')
    trigger = interp.get('_insight_trigger', '')

    if ct == 'blocker_insight':
        bf = facts.get('blocker_facts', {})
        if not bf.get('enabled'):
            reasons.append('E1: blocker insight without blocker_facts enabled')
        board = facts.get('board', {}).get('cards', [])
        if len(board) < 3:
            reasons.append('E1: blocker insight without sufficient board')
        if trigger == 'no_flush_blocker' and not bf.get('no_flush_blocker'):
            reasons.append('E2: no_flush_blocker card without no_flush_blocker fact')
        if trigger == 'nut_flush_blocker' and bf.get('hero_has_made_flush'):
            reasons.append('E3: nut_flush_blocker rendered when hero has made flush')
        if trigger == 'paired_board_blocker' and not bf.get('paired_board_blocker'):
            reasons.append('E4: paired_board_blocker card without paired_board_blocker fact')

    if ct == 'range_awareness':
        hrf = facts.get('hero_range_facts', {})
        if not hrf.get('enabled'):
            reasons.append('F1: range awareness without hero_range_facts enabled')
        if trigger == 'outside_chart' and hrf.get('range_context') != 'open':
            reasons.append('F2: outside-chart card in non-open context')
        if trigger == 'capped_premium' and hrf.get('range_context') not in ('flat_vs_open', 'cold_call'):
            reasons.append('F3: capped-premium card in wrong context')
        if trigger == 'premium_early':
            pos = facts.get('hero', {}).get('position', '')
            if pos not in _EP_POSITIONS or hrf.get('range_position') != 'premium':
                reasons.append('F4: premium-early card without EP premium')

    return len(reasons) == 0, reasons


# ── display card builder ──────────────────────────────────────────

def _build_display_card(facts, gates, interp, confidence):
    """Assemble final display_card dict."""
    # v8.17.1 Iter-1: a template may PIN the card's decision street. The PKO
    # bounty-pressure card is a PREFLOP defend/jam concept; without this it inherited
    # facts['street'] (Hero's last-action street) and rendered "PKO Review" on the
    # flop/river (83793494 river value-bet, 84295953 flop fold).
    _street = interp.get('street') or facts['street']
    return {
        'card_id': _card_id(facts['hand_id'], _street, interp['card_type']),
        'hand_id': facts['hand_id'],
        'street': _street,
        'card_type': interp['card_type'],
        'poker_verdict': interp['poker_verdict'],
        'headline': interp['headline'],
        'why': interp['why'],
        'learn': interp['learn'],
        'plan': interp['plan'],
        'metrics': interp.get('metrics', []),
        'ranges': interp.get('ranges', []),
        'warnings': interp.get('warnings', []),
        'variant': interp.get('variant', ''),
        'display_confidence': confidence,
        'provenance': facts['provenance'],
        # REV9 C2: the selected reviewed action this card's decision facts derive from
        # (the consumer-ownership inventory proves coaching-card bounty context is the
        # reviewed action, never the hand-level default).
        'reviewed_action_index': facts.get('reviewed_action_index'),
        'bounty_context_owner': facts.get('bounty_context_owner'),
    }


# ── claim reconciliation ─────────────────────────────────────────

def _reconcile(card, report_data, punt_ids, mistake_ids):
    """Check card against existing flags.  Returns card or None."""
    hid = card.get('hand_id', '')
    verdict = card.get('poker_verdict', '')

    if hid in punt_ids and 'Good' in verdict:
        return None
    if hid in mistake_ids and 'Good' in verdict:
        return None

    return card


# ── entry point ───────────────────────────────────────────────────

def build_coaching_cards(hands, stats, report_data, ranges=None):
    """Build coaching display_cards for all eligible hands.

    Returns dict mapping hand_id -> list[display_card].
    Mutates nothing.
    """
    _tmpl_pko_pressure._count = 0  # v8.12.1 per-report cap reset
    if not hands:
        return {}

    punt_ids = set()
    if isinstance(stats, dict):
        punts = stats.get('punts', {})
        if isinstance(punts, dict):
            _ph = punts.get('hands', [])
            punt_ids = {(p.get('id', '') if isinstance(p, dict) else p) for p in _ph}
        elif isinstance(punts, list):
            punt_ids = {p.get('id', '') for p in punts if isinstance(p, dict)}

    mistake_ids = set()
    if isinstance(stats, dict):
        mistakes = stats.get('mistakes', [])
        if isinstance(mistakes, list):
            mistake_ids = {m.get('id', '') for m in mistakes if isinstance(m, dict)}
        elif isinstance(mistakes, dict):
            _mh = mistakes.get('hands', [])
            mistake_ids = {(m.get('id', '') if isinstance(m, dict) else m) for m in _mh}

    eai_ids = set()
    if isinstance(stats, dict):
        eai = stats.get('eai', {})
        if isinstance(eai, dict):
            for eh in eai.get('hands', []):
                if isinstance(eh, dict) and eh.get('id'):
                    eai_ids.add(eh['id'])

    result = {}
    for h in hands:
        if not isinstance(h, dict):
            continue
        hid = h.get('id', '')
        if not hid:
            continue
        _pko_cls = (h.get('pko_context') or {}).get('classification')
        if not _is_eligible(h, punt_ids, mistake_ids, eai_ids)                 and _pko_cls not in ('Missed', 'Review'):
            # v8.12.1: PKO Review/Missed hands are insight-eligible even when
            # they carry no punt/mistake/EAI flag (they are routine defends
            # by definition — that's what the teaching layer is FOR).
            continue

        facts = _build_decision_facts(h, stats, report_data)
        _compute_blocker_facts(facts)
        _compute_hero_range_facts(facts, ranges)
        gates, confidence, suppress = derive_quality_gates(facts)

        if not suppress:
            interp = _select_template(facts, gates)
            if interp is not None:
                ok, reasons = _run_assertions(facts, gates, interp)
                if ok:
                    card = _build_display_card(facts, gates, interp, confidence)
                    card = _reconcile(card, report_data, punt_ids, mistake_ids)
                    if card is not None:
                        result.setdefault(hid, []).append(card)

        insight = _select_insight(facts, gates)
        if insight is not None:
            ok_i, reasons_i = _run_assertions(facts, gates, insight)
            if ok_i:
                icard = _build_display_card(facts, gates, insight, confidence)
                icard = _reconcile(icard, report_data, punt_ids, mistake_ids)
                if icard is not None:
                    result.setdefault(hid, []).append(icard)

    return result
