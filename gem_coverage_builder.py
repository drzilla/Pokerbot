"""Coverage candidate builder + analyst worksheet emitter.

Extracted from gem_analyzer.py __main__ (v8.9.9) to enable
--resume-from-cache without re-running the full analyze pass.

Usage:
    from gem_coverage_builder import build_and_write
    candidates = build_and_write(stats, hands, report_data, ...)
"""

import json
import os
import time as _time

from gem_parser import normalize_hand, RANK_NUM
# v8.14.1 hotfix (#71725727): human-readable chart labels, never raw chart ids.
from gem_chart_labels import chart_display_label

_PUSH_RANGES = {
    ('SB', True):  'PP, Ax, Kx, Qx, suited, connected',
    ('SB', False): 'PP, Ax, Kx, suited Qx+/connected/5+',
    ('BB', True):  'PP, Ax, Kx, Qx, suited, connected',
    ('BB', False): 'PP, Ax, Kx, suited Qx+/connected/5+',
    ('BTN', True): 'PP, Ax, Kx, suited, broadway, J+x',
    ('BTN', False):'PP, Ax, Kx, suited 6+, broadway',
    ('CO', True):  'PP, Ax, Kx (incl. offsuit), suited K+, broadway',
    ('CO', False): 'PP, Ax, Kx (incl. offsuit), suited K/Q, broadway T+',
    ('HJ', True):  'PP 4+, A8+, suited KT+',
    ('HJ', False): 'PP 4+, A8+, suited KT+',
}

def _is_core_push(hs, pos, stack_bb):
    if stack_bb >= 8 or not hs or len(hs) < 2:
        return False, ''
    is_pair = len(hs) == 2
    is_suited = len(hs) == 3 and hs[2] == 's'
    is_ace = hs[0] == 'A'
    is_king = hs[0] == 'K'
    r1 = RANK_NUM.get(hs[0], 0)
    r2 = RANK_NUM.get(hs[1], 0)
    is_core = False
    if pos in ('SB', 'BB'):
        is_core = is_ace or is_king or is_pair
    elif pos == 'BTN':
        if stack_bb < 5:
            is_core = is_ace or is_pair or is_king
        else:
            is_core = is_ace or is_pair
    elif pos == 'CO':
        is_core = is_ace or is_pair or is_king
    elif pos == 'HJ':
        is_core = (is_ace and r2 >= 10) or (is_pair and r1 >= 7)
    pr = _PUSH_RANGES.get((pos, stack_bb < 5),
                          _PUSH_RANGES.get((pos, False), ''))
    return is_core, pr


# v8.13.1 P1: postflop-loss coverage threshold. Single configurable point —
# a hand that lost at least this many BB postflop is force-screened into the
# worklist so ANALYST_COMPLETE cannot be claimed while it is unreviewed.
POSTFLOP_LOSS_SCREEN_BB = -15.0


def _reached_flop_h(h):
    """True iff Hero saw a flop (had a postflop decision). Board is a list of
    community cards; a showdown also implies postflop. Used to exclude
    preflop-only losses from the postflop-loss screen."""
    b = h.get('board') or []
    if isinstance(b, (list, tuple)):
        n = len(b)
    else:
        n = len(str(b).replace(' ', '')) // 2
    return n >= 3 or bool(h.get('went_to_sd'))


def build_loss_screens(stats, hands, postflop_threshold_bb=POSTFLOP_LOSS_SCREEN_BB,
                       strict=True):
    """v8.13.1 P1 (analyst-coverage trust): force critical-loss hands into the
    review set. Pure + testable — returns id lists, no rendering / no candidate
    context. Two coverage screens (NOT mistake detectors):

      biggest_loss_screen   — every stack_trajectories[*].biggest_loss_id that
                              is an actual loss (the 2026-06-13 gap: a
                              per-tournament biggest loss, TM6072806503, was
                              absent from the worklist though correctly cleared
                              on manual review).
      postflop_loss_screen  — every hand with net_bb <= threshold that reached
                              the flop and was NOT a preflop all-in (the
                              missing -40/-26/-19BB postflop losses).

    A hand is screened into at most one bucket (biggest-loss wins) so the
    worklist does not double-count it.
    """
    hands_by_id = {h.get('id'): h for h in (hands or [])}
    seen, biggest, postflop = set(), [], []
    # v8.19.0 Chapter G (ANA-001): fail loud, do not silent-skip. A tournament with NO
    # biggest_loss_id is legitimately absent; but a NAMED biggest_loss_id that is missing
    # from hands or is not a net loss is a payload/schema mismatch — collect and (strict)
    # raise with the named id + reason so count == payload == rendered can never silently drift.
    _violations = []
    for _tid, _traj in (stats.get('stack_trajectories', {}) or {}).items():
        blid = (_traj or {}).get('biggest_loss_id')
        if not blid or blid in seen:
            continue                              # absent / already screened -> fine
        h = hands_by_id.get(blid)
        if h is None:
            _violations.append("%s (tournament %s): named biggest_loss_id missing from hands"
                               % (blid, _tid))
            continue
        if (h.get('net_bb') or 0) >= 0:
            _violations.append("%s (tournament %s): named biggest_loss_id is not a net loss "
                               "(net_bb=%s)" % (blid, _tid, h.get('net_bb')))
            continue
        seen.add(blid)
        biggest.append(blid)
    if _violations and strict:
        raise ValueError("ANA-001 SCHEMA: biggest_loss_screen payload mismatch — "
                         + "; ".join(_violations))
    for h in (hands or []):
        hid = h.get('id')
        if not hid or hid in seen or h.get('pf_allin'):
            continue
        if (h.get('net_bb') or 0) > postflop_threshold_bb:   # threshold is negative
            continue
        if not _reached_flop_h(h):
            continue
        seen.add(hid)
        postflop.append(hid)
    return {'biggest_loss_screen': biggest, 'postflop_loss_screen': postflop,
            'biggest_loss_violations': _violations}


def build_and_write(stats, hands, report_data, pname_file, session_dir,
                    ranges=None, timing=None):
    """Build analyst candidates, auto-verdicts, worksheet. Mutates report_data in place.

    Returns the candidates dict.
    """
    _pname_file = pname_file
    SESSION_DIR = session_dir
    _timing = timing or {}
    _t_parse = _timing.get('parse_s', 0)
    _t_analyze = _timing.get('analyze_s', 0)
    _t_profiler = _timing.get('profiler_s')
    _t_verdict = _timing.get('verdicts_s')
    _t_render = _timing.get('render_s')
    _t_pipeline_start = _timing.get('pipeline_start', _time.perf_counter())

    # ---- ANALYST CANDIDATES (v7.36) ----
    # Pipeline emits typed buckets of hands flagged as needing qualitative
    # review. This file is the input contract for the analyst step (Claude
    # examines candidates, writes session_analysis_<date>.json).
    # Renderer reads session_analysis_*.json (if present) and stitches
    # commentary into bust audit / I.7 cooler notes / III.4 read-dependent.
    cand_path = f'/home/claude/analyst_candidates_{_pname_file}_{stats["volume"]["date_range"]}.json'
    candidates = {
        'session_date': stats['volume']['date'],
        'date_compact': stats['volume']['date_range'],
        'bust_audit': [],
        'coolers': [],
        'mistakes': [],
        'punts': [],
        'iii4_screening': [],
        'read_dependent_screening': [],
        'bestplay_screening': [],
        'big_river_calldowns': [],
        # v8.13.1 P1: coverage screens — force critical-loss hands into review.
        'biggest_loss_screen': [],
        'postflop_loss_screen': [],
    }
    hands_by_id = {h.get('id'): h for h in hands}
    # RC3 P0-2: compute the canonical loss screens EARLY — before auto-resolution AND before the
    # analyst_candidates_*.json contract is written. Previously build_loss_screens ran ~230 lines
    # AFTER the file write, so the persisted biggest_loss_screen / postflop_loss_screen buckets
    # always shipped EMPTY, and the session's largest losses could be auto-resolved out of review.
    # Computing the mandatory-loss id set here lets us (a) populate the persisted buckets and
    # (b) NEVER auto-resolve a mandatory biggest/postflop loss.
    _loss_screens = build_loss_screens(stats, hands)
    _mandatory_loss_ids = (set(_loss_screens['biggest_loss_screen'])
                           | set(_loss_screens['postflop_loss_screen']))
    # Build EAI lookup BEFORE _hand_ctx (hero_realized_eq_at_allin needs it)
    _eai_by_id_pf = {}
    for _e in (stats.get('eai', {}).get('hands', []) or []):
        _eai_by_id_pf[_e.get('id', '')] = _e
    def _pairwise_eff(h):
        """BUG-H: compute pairwise effective stack vs the villain Hero is facing.
        For call-of-jam: min(Hero stack, jammer stack).
        Fallback: eff_stack_bb_at_decision (table-wide min)."""
        _pe = h.get('eff_stack_bb_at_decision')
        # If Hero called a jam, find the jammer's stack
        _jpos = h.get('jammer_position')
        _jstk = h.get('jammer_stack_bb')
        if _jstk and h.get('stack_bb'):
            _pe = min(h['stack_bb'], _jstk)
        elif not _pe:
            # Fallback: check action ledger for the villain who bet/raised all-in
            for _a in reversed(h.get('action_ledger') or []):
                if (_a.get('is_all_in') and _a.get('action') in ('raises', 'bets')
                        and _a.get('player') != h.get('hero')):
                    _v_stk = _a.get('stack_bb', 0)
                    if _v_stk and h.get('stack_bb'):
                        _pe = min(h['stack_bb'], _v_stk)
                    break
        return _pe or h.get('eff_stack_bb') or h.get('stack_bb') or 0

    def _build_action_sequence(h):
        """Build a compact per-street action sequence showing initiative.
        e.g. 'flop: Hero cbet 33% → villain call | turn: villain x/r → Hero jam'
        """
        _hero = h.get('hero', '')
        _seq = []
        for street in ('flop', 'turn', 'river'):
            _acts = []
            for a in (h.get('action_ledger') or []):
                if a.get('street') != street:
                    continue
                _player = 'Hero' if a.get('player') == _hero else 'V'
                _action = a.get('action', '?')
                _amt = a.get('amount_bb')
                _ai = ' AI' if a.get('is_all_in') else ''
                if _amt and _action in ('bets', 'raises'):
                    _acts.append(f'{_player} {_action} {_amt:.1f}BB{_ai}')
                elif _action in ('checks',):
                    _acts.append(f'{_player} x')
                elif _action in ('calls',):
                    _acts.append(f'{_player} call{_ai}')
                elif _action in ('folds',):
                    _acts.append(f'{_player} fold')
            if _acts:
                _seq.append(f'{street}: {" → ".join(_acts)}')
        return ' | '.join(_seq) if _seq else ''

    def _hand_ctx(hid):
        h = hands_by_id.get(hid)
        if not h: return {'id': hid, 'missing_in_set': True}
        # v7.37 Bug#7 fix: emit EFFECTIVE stack at the decision (not just hero's
        # starting stack) so analysts don't anchor on the wrong number.
        # v7.37 Bug#8 fix: emit hero_street_actions + line_actions + villain
        # x/r flags so analysts can't misread "cbet-bet" lines as "x/r AI call".
        # Both surfaced 2026-05-08 when comparing prior-pass commentary against
        # actual hand histories — anchoring on hero's stack flipped the verdict
        # on TM5922893739 (99 BTN), and the prior-pass author misread two
        # bust hands (QJo / KQo) as "turn x/r AI call" when hero was the
        # bettor on turn (line_actions = cbet-bet for both).
        seat_stacks = {'Hero': h.get('stack_bb')}
        for pos_label, sb in (h.get('stacks_behind') or {}).items():
            seat_stacks[pos_label] = sb
        return {
            'id': hid,
            'tournament': h.get('tournament'),
            'date': h.get('date'),
            'position': h.get('position'),
            'stack_bb': h.get('stack_bb'),                      # hero's stack
            'effective_stack_bb': h.get('eff_stack_bb'),        # min at start (table-wide)
            # BUG-H: pairwise effective stack vs the villain Hero is facing.
            # For call-of-jam spots, eff stack should be min(Hero, jammer),
            # not table minimum which may be a side-pot short stack.
            'eff_stack_at_decision_bb': _pairwise_eff(h),
            # EAI equity at all-in (for §3b math — the analyst's #1 need)
            'hero_realized_eq_at_allin': ((_eai_by_id_pf.get(hid) or {}).get('hero_equity')
                                 if hid in _eai_by_id_pf else None),
            'hero_committed_bb': h.get('hero_committed_bb'),
            'seat_stacks_bb': seat_stacks,
            'jammer_position': h.get('jammer_position'),
            'jammer_stack_bb': h.get('jammer_stack_bb'),
            'cards': ''.join(h.get('cards', [])),
            'board': h.get('board', ''),
            'pf_sequence': h.get('pf_sequence', ''),
            'action_summary': h.get('action_summary', ''),
            'hero_street_actions': h.get('hero_street_actions', {}),
            'line_actions': h.get('line_actions', ''),
            'villain_xr_flop': h.get('villain_xr_flop', False),
            'villain_xr_turn': h.get('villain_xr_turn', False),
            'villain_xr_river': h.get('villain_xr_river', False),
            'net_bb': h.get('net_bb', 0),
            'went_to_sd': h.get('went_to_sd', False),
            'pf_allin': h.get('pf_allin', False),
            'n_players': h.get('n_players'),
            'tournament_phase': h.get('tournament_phase', ''),
            # B253 (split-verdict): per-street per-node committed amounts
            # for bet-then-call-raise streets. Lets analyst assign separate
            # verdicts per decision node with correct magnitude attribution.
            'hero_street_nodes': h.get('hero_street_nodes', {}),
            'tournament_phase': h.get('tournament_phase', ''),
            'format': h.get('format', ''),        # BOUNTY/FREEZEOUT/SATELLITE
            'pot_type': h.get('pot_type', ''),     # SRP/3BP/4BP
            'spr': h.get('spr'),                   # stack-to-pot ratio at flop
            'hand_strength': h.get('hand_strength', ''),  # final made-hand class
            'won': h.get('won'),                   # True/False/None
            'players_at_flop': h.get('players_at_flop', 0),
            'table_size': h.get('table_size', 0),
            'level': h.get('level'),
            'board_texture': h.get('board_texture', ''),   # dry/wet/monotone
            'board_archetype': h.get('board_archetype', ''),  # GTO archetype
            # Preflop action flags
            'vpip': h.get('vpip', False),
            'pfr': h.get('pfr', False),
            'first_in': h.get('first_in', False),
            'hero_3bet': h.get('hero_3bet', False),
            'cold_called': h.get('cold_called', False),
            'opener_position': h.get('opener_position', ''),
            # Postflop action flags
            'hero_cbet_flop': h.get('hero_cbet_flop', False),
            'faced_villain_cbet_flop': h.get('faced_villain_cbet_flop', False),
            'double_barreled': h.get('double_barreled', False),
            'triple_barreled': h.get('triple_barreled', False),
            'check_raises': h.get('check_raises', []),
            # Bounty estimation for §3b math
            'bounty_type': h.get('bounty_type', 'none'),
            'bounty_discount_pp': h.get('bounty_discount_pp', 0),
            'bounty_value_bb': h.get('bounty_value_bb', 0),
            'bounty_label': h.get('bounty_label', ''),
            # BUG-3 wiring: per-street draw profile for analyst context.
            'draw_profiles': _compute_draw_profiles(h),
            # v8.7.7: board-centric per-street state (flush/paired/straight facts)
            'board_state': _compute_board_state(h),
            # Opponent archetype: villain classification for exploit awareness
            'villain_archetype': h.get('villain_archetype', ''),       # raw code: NIT/STATION/etc
            'villain_archetype_label': h.get('villain_archetype_label', ''),  # emoji + name
            'villain_archetype_reason': h.get('villain_archetype_reason', ''),  # stats: VPIP/PFR/AF/SD%
            'villain_exploit_note': h.get('villain_exploit_note', ''),
            # v8.4.0: villain shown cards + action sequence for analyst efficiency
            'villain_shown_cards': ((h.get('primary_villain', {}) or {}).get('shown_cards', [])
                or next((v.get('shown_cards', []) for v in (h.get('villains', {}) or {}).values()
                         if v.get('shown_cards')), [])),
            'action_sequence': _build_action_sequence(h),
        }

    def _compute_draw_profiles(h):
        """Compute draw_profile at each postflop street for a hand."""
        try:
            from gem_made_hands import draw_profile as _dp
        except Exception:
            return {}
        hero_cards = h.get('cards', [])
        board = h.get('board', [])
        if not isinstance(hero_cards, list) or len(hero_cards) != 2:
            return {}
        if not isinstance(board, list) or len(board) < 3:
            return {}
        profiles = {}
        for st, n in [('flop', 3), ('turn', 4), ('river', 5)]:
            if len(board) >= n:
                p = _dp(hero_cards, board[:n])
                if p:
                    profiles[st] = p.get('summary', '')
        return profiles

    def _compute_board_state(h):
        """Compute board-centric per-street state (v8.7.7)."""
        try:
            from gem_board_state import board_state as _bs
        except Exception:
            return {}
        board = h.get('board', [])
        hero = h.get('cards', [])
        if not isinstance(board, list) or len(board) < 3:
            return {}
        return _bs(board, hero if isinstance(hero, list) and len(hero) == 2 else None)

    # Bust audit candidates (>25BB lost). B239 (v7.99.22, Ron review
    # 2026-05-26): the flat -25BB cut missed genuine busts of short stacks —
    # 00648109 (JJ stacked off for 22.8BB and lost) never reached the audit.
    # Also flag any hand where Hero committed essentially the whole stack and
    # lost, regardless of BB magnitude: a lost stack-off IS a bust.
    _bust_seen = set()
    for h in hands:
        hid = h['id']
        big_loss = h.get('net_bb', 0) < -25
        stack = h.get('stack_bb') or 0
        committed = h.get('hero_committed_bb') or 0
        stacked_off = (stack > 0 and committed >= stack * 0.95
                       and not h.get('won')
                       and (h.get('pf_allin') or h.get('went_to_sd')))
        if (big_loss or stacked_off) and hid not in _bust_seen:
            _bust_seen.add(hid)
            candidates['bust_audit'].append(_hand_ctx(hid))
    # Cooler candidates (auto-flagged)
    for c in stats.get('coolers', {}).get('hands', []) or []:
        cid = c.get('id') or c.get('hand_id')
        if cid:
            ctx = _hand_ctx(cid)
            ctx.update({'cooler_kind': c.get('kind'), 'street': c.get('street')})
            candidates['coolers'].append(ctx)
    # B252 (bust-classification fix, Bug 1): postflop variance-outcome
    # classifier. Runs over eai_list for all-in-to-showdown hands that are
    # NOT coolers and were LOST by Hero. Assigns a suggested outcome label
    # (suckout/lost_flip/top_of_range/semi_bluff_cooler) so:
    #   (a) the bust-audit candidate context carries a default for the analyst
    #   (b) the renderer's equity auto-tagger can consume it
    # Uses existing eai_entry fields (suckout, hero_equity, category,
    # is_favorite) — does NOT recompute equity.
    _cooler_ids = {c.get('id') or c.get('hand_id')
                   for c in (stats.get('coolers', {}).get('hands', []) or [])}
    _variance_outcomes = {}  # hid → outcome label
    _eai_hands = stats.get('eai', {}).get('hands', []) or []
    for _ve in _eai_hands:
        _vid = _ve.get('id')
        if not _vid or _vid in _cooler_ids:
            continue
        if _ve.get('won') is not False:
            continue  # only classify LOST hands
        _veq = _ve.get('hero_equity')
        _vfav = _ve.get('is_favorite', False)
        _vcat = _ve.get('category', '')
        _vsuckout = _ve.get('suckout', '')
        _voc = None
        # Priority 1: use the existing suckout field from gem_eai_equity
        if _vsuckout == 'against_hero':
            _voc = 'suckout'
        # Priority 2: equity-band classification (multiway-aware)
        # Fair share = 1/n_players. Flip = within ±8pp of fair share.
        # HU: fair=50, flip=42-58. 3-way: fair=33, flip=25-41.
        elif _veq is not None:
            _n_ai = _ve.get('n_allin', 2) or 2
            _fair = 1.0 / _n_ai
            _flip_lo = _fair - 0.08
            _flip_hi = _fair + 0.08
            _suckout_floor = _fair + 0.12  # need to be >12pp above fair share
            if _vfav and _veq >= _suckout_floor:
                _voc = 'suckout'        # Hero was dominating, got sucked out
            elif _flip_lo <= _veq <= _flip_hi or _vcat == 'flip':
                _voc = 'lost_flip'      # coin-flip band (multiway-adjusted)
            elif _veq < _flip_lo and not _vfav:
                # Hero was behind — if the hand was a mandatory get-in
                # (pf_allin or stacked off), it's 'top_of_range' (ran into
                # the top of villain's range). Otherwise semi_bluff_cooler.
                _vh = hands_by_id.get(_vid)
                if _vh and (_vh.get('pf_allin') or
                            (_vh.get('hero_committed_bb') or 0) >=
                            ((_vh.get('stack_bb') or 0) * 0.85)):
                    _voc = 'top_of_range'
                else:
                    _voc = 'semi_bluff_cooler'
        if _voc:
            _variance_outcomes[_vid] = {
                'outcome': _voc,
                'hero_equity': _veq,
                'is_favorite': _vfav,
                'n_allin': _ve.get('n_allin', 2),
                'villain_hand': _ve.get('villain_hand', ''),
            }
    # Enrich bust-audit candidates with the suggested outcome
    for _bc in candidates['bust_audit']:
        _bcid = _bc.get('id')
        if _bcid and _bcid in _variance_outcomes:
            _bc['suggested_outcome'] = _variance_outcomes[_bcid]
    def _voc_label(v):
        return v['outcome'] if isinstance(v, dict) else v
    if _variance_outcomes:
        print(f"  variance-outcome classifier: {len(_variance_outcomes)} "
              f"all-in losses tagged "
              f"({sum(1 for v in _variance_outcomes.values() if _voc_label(v)=='suckout')} "
              f"suckout, "
              f"{sum(1 for v in _variance_outcomes.values() if _voc_label(v)=='lost_flip')} "
              f"lost_flip, "
              f"{sum(1 for v in _variance_outcomes.values() if _voc_label(v)=='top_of_range')} "
              f"top_of_range, "
              f"{sum(1 for v in _variance_outcomes.values() if _voc_label(v)=='semi_bluff_cooler')} "
              f"semi_bluff_cooler)")
    # Surface variance outcomes to report_data for the renderer
    report_data['variance_outcomes'] = _variance_outcomes

    # ------------------------------------------------------------------
    # Issue 6 (Ron 2026-05-30): CHART-MATCH AUTO-RESOLVE
    # Tag bust-audit hands that are chart-standard <8BB open-jams so the
    # coverage gate excludes them. Conditions (ALL must hold):
    #   1. pf_allin = True (preflop all-in, not postflop bust)
    #   2. stack_bb < 8 (ultra-short — chart is authoritative)
    #   3. first_in = True, pfr = True (open-jam, not reshove)
    #   4. hand is in CORE push range (CLEAR confidence, not MARGINAL)
    #   5. NOT in ICM phase (bubble/post_bubble/ft_zone)
    #   6. has a variance outcome (lost_flip/suckout/top_of_range)
    # ------------------------------------------------------------------
    _auto_resolved_ids = set()
    _auto_resolved_n = 0
    for _bc in candidates['bust_audit']:
        _bcid = _bc.get('id')
        if not _bcid:
            continue
        _bh = hands_by_id.get(_bcid)
        if not _bh:
            continue
        _bstack = _bh.get('stack_bb') or 99
        if _bstack >= 8:
            continue
        if not _bh.get('pf_allin'):
            continue
        if not _bh.get('first_in') or not _bh.get('pfr'):
            continue
        _bicm = _bh.get('icm_pressure', 0) or 0
        if _bicm >= 0.5:
            continue
        if _bcid not in _variance_outcomes:
            continue
        _bhs = normalize_hand(_bh.get('cards', []))
        _bpos = _bh.get('position', '')
        _core_ok, _core_range = _is_core_push(_bhs, _bpos, _bstack)
        if not _core_ok:
            continue
        # All conditions met — tag as auto-resolved
        _voc_raw = _variance_outcomes[_bcid]
        _voc_label = (_voc_raw['outcome'] if isinstance(_voc_raw, dict) else _voc_raw).replace('_', ' ')
        _bc['auto_verdict'] = 'chart_standard'
        _bc['auto_verdict_label'] = (
            f"✅ chart-standard open-jam "
            f"({_bpos} {round(_bstack)}BB {_bhs}) — {_voc_label}")
        _bc['auto_verdict_range'] = _core_range
        _auto_resolved_ids.add(_bcid)
        _auto_resolved_n += 1
    if _auto_resolved_n:
        print(f"  chart-match auto-resolve: {_auto_resolved_n} bust-audit hands "
              f"tagged chart-standard (excluded from coverage gate)")

    # ------------------------------------------------------------------
    # Auto-resolve #2 (Ron 2026-05-30): STANDARD PREFLOP ALL-IN VARIANCE
    # Preflop all-ins with standard 3b/4b lines that lost to variance
    # (lost_flip or suckout). Conditions:
    #   1. pf_allin = True (pure preflop all-in, no postflop)
    #   2. has a variance outcome: lost_flip or suckout
    #   3. no detector flag (P1-P6 didn't fire — not a Wide/CVJ/etc)
    #   4. NOT already chart-match resolved
    #   5. eff_stack < 30BB (standard get-in territory)
    #   6. no board (pure preflop — if there's a board, postflop decisions
    #      may matter and need analyst review)
    # These are the hands where the analyst rubber-stamps "variance" anyway.
    # ------------------------------------------------------------------
    _punted_id_set = {p.get('id') for p in (stats.get('punts', {}).get('hands', []) or [])}
    _pf_variance_n = 0
    for _bc in candidates['bust_audit']:
        _bcid = _bc.get('id')
        if not _bcid or _bcid in _auto_resolved_ids:
            continue
        _bh = hands_by_id.get(_bcid)
        if not _bh:
            continue
        if not _bh.get('pf_allin'):
            continue
        # Must have a clean variance outcome (not top_of_range/semi_bluff_cooler
        # — those need analyst review for whether Hero should have been there)
        _voc_raw = _variance_outcomes.get(_bcid)
        _voc = _voc_raw['outcome'] if isinstance(_voc_raw, dict) else _voc_raw
        if _voc not in ('lost_flip', 'suckout'):
            continue
        # No detector flag — if P1-P6 fired, the analyst needs to review
        if _bcid in _punted_id_set:
            continue
        # Effective stack < 30BB — deeper stacks may involve non-standard lines
        _bstack = _bh.get('eff_stack_bb_at_decision') or _bh.get('eff_stack_bb') or _bh.get('stack_bb') or 99
        if _bstack >= 30:
            continue
        # No board cards — pure preflop all-in
        _bboard = _bh.get('board') or []
        if _bboard and len(_bboard) > 0:
            # Board exists = went to showdown postflop — but since pf_allin
            # is True, the board was dealt after the money went in. This is
            # fine — the decision was preflop. Allow it.
            pass
        _voc_label = _voc.replace('_', ' ')
        _bc['auto_verdict'] = f'pf_variance_{_voc}'
        _bhands = normalize_hand(_bh.get('cards', []))
        _bpos = _bh.get('position', '?')
        _bc['auto_verdict_label'] = (
            f"✅ standard preflop all-in — {_voc_label} "
            f"({_bpos} {round(_bstack)}BB {_bhands})")
        _auto_resolved_ids.add(_bcid)
        _pf_variance_n += 1
    if _pf_variance_n:
        print(f"  pf-variance auto-resolve: {_pf_variance_n} preflop all-in "
              f"lost-flips/suckouts tagged (excluded from coverage gate)")

    # ------------------------------------------------------------------
    # Auto-resolve #3 (Ron 2026-05-30): COOLER-DETECTOR MATCH
    # Hands the cooler detector already identified (pair-over-pair,
    # set-over-set, flush-over-flush etc.) that are also in the bust audit.
    # These are structural matchups — the analyst almost always assigns
    # I.7 Cooler. Conditions:
    #   1. hand is in the cooler detector output (s['coolers']['hands'])
    #   2. hand is in the bust-audit candidates
    #   3. Hero committed ≥ 20BB (not a trivial pot)
    #   4. NOT already resolved by chart-match or pf-variance
    # ------------------------------------------------------------------
    _cooler_n = 0
    for _bc in candidates['bust_audit']:
        _bcid = _bc.get('id')
        if not _bcid or _bcid in _auto_resolved_ids:
            continue
        if _bcid not in _cooler_ids:
            continue
        _bh = hands_by_id.get(_bcid)
        if not _bh:
            continue
        # Must have committed meaningful chips
        _committed = _bh.get('hero_committed_bb') or abs(_bh.get('net_bb', 0))
        if _committed < 20:
            continue
        # Find the cooler entry for the label
        _cooler_entry = next(
            (c for c in (stats.get('coolers', {}).get('hands', []) or [])
             if c.get('id') == _bcid), None)
        _ckind = (_cooler_entry.get('kind', 'cooler') if _cooler_entry
                  else 'cooler')
        _bc['auto_verdict'] = 'cooler_detected'
        _bc['auto_verdict_label'] = f"❄️ cooler-detector match — {_ckind}"
        _auto_resolved_ids.add(_bcid)
        _cooler_n += 1
    if _cooler_n:
        print(f"  cooler auto-resolve: {_cooler_n} cooler-detector hands "
              f"tagged (excluded from coverage gate)")

    # RC3 P0-2: a mandatory biggest/postflop loss must NEVER be auto-resolved out of review,
    # regardless of which detector tagged it — restore any that an auto-resolver swept up.
    _swept = _auto_resolved_ids & _mandatory_loss_ids
    if _swept:
        _auto_resolved_ids -= _mandatory_loss_ids
        print(f"  RC3 P0-2: restored {len(_swept)} mandatory loss hand(s) from auto-resolve "
              f"(biggest/postflop loss must be reviewed)")
    report_data['auto_resolved_ids'] = sorted(_auto_resolved_ids)
    # Expose per-hand auto-verdict labels for the renderer
    _auto_labels = {}
    for _bc in candidates['bust_audit']:
        _bcid = _bc.get('id')
        if _bcid and _bcid in _auto_resolved_ids and _bc.get('auto_verdict_label'):
            _auto_labels[_bcid] = _bc['auto_verdict_label']
    report_data['auto_resolved_labels'] = _auto_labels

    # Mistake candidates (auto-detector hits worth narrative review)
    for m in stats.get('mistakes', []) or []:
        mid = m.get('id')
        if mid:
            ctx = _hand_ctx(mid)
            ctx.update({'mistake_type': m.get('type'),
                        'confidence': m.get('confidence', 'MARGINAL'),
                        'mistake_severity': m.get('confidence', m.get('severity', 'MARGINAL'))})
            candidates['mistakes'].append(ctx)
    # D2: Bad river call-downs surface as mistakes
    for _bcd in stats.get('bad_river_calldowns', []) or []:
        _bcd_id = _bcd.get('id')
        if _bcd_id and _bcd_id not in _bust_seen:
            ctx = _hand_ctx(_bcd_id)
            ctx['mistake_type'] = 'Bad River Call-Down'
            ctx['confidence'] = 'CLEAR'
            ctx['mistake_severity'] = 'CLEAR'
            ctx['bad_calldown'] = _bcd
            candidates['mistakes'].append(ctx)

    # Punt candidates (v7.71, Ron 2026-05-23): the Px punt patterns are a
    # SEPARATE stream from `mistakes` — punted ids are removed from `mistakes`
    # to avoid double-count, so detector punts were never surfaced to the
    # analyst step. They reached the III.1 section with NO analyst commentary
    # ("auto-detector" source). Route every detector punt here: the analyst
    # reviews ALL of them and writes a verdict (III.1 confirm, or III.3/4/5
    # overturn). The detector remains a backend efficiency process, invisible
    # to the reader — what the user sees is the analyst's verdict.
    for pnt in (stats.get('punts', {}) or {}).get('hands', []) or []:
        pid = pnt.get('id')
        if pid:
            ctx = _hand_ctx(pid)
            ctx.update({'punt_pattern': pnt.get('pattern'),
                        'punt_type': pnt.get('type'),
                        'punt_reason': pnt.get('reason'),
                        'punt_committed_bb': pnt.get('committed_bb'),
                        'punt_net_bb': pnt.get('net_bb')})
            candidates['punts'].append(ctx)
    # III.4 screening: bust hands that aren't clear coolers — likely candidates
    # for read-dependent reasoning. Analyst step decides whether they belong.
    # B252 (bust-classification fix): exclude all-in-to-showdown hands from
    # iii4_screening. A hand that went all-in and reached showdown is a
    # variance/cooler/suckout event, not a read-dependent decision. These
    # are classified by the cooler detector + variance-outcome classifier
    # (Bug 1). Defence in depth: the analyst-load validator (work-order
    # Item 1) also catches misclassified forced all-ins at load time.
    cooler_ids_set = {c.get('id') or c.get('hand_id')
                      for c in (stats.get('coolers', {}).get('hands', []) or [])}
    # All-in-to-showdown IDs: any hand in eai 'hands' went all-in AND reached
    # showdown (the eai builder requires both went_to_sd and hero all-in).
    _allin_sd_ids = {e['id'] for e in (stats.get('eai', {}).get('hands', []) or [])}
    for h in hands:
        hid = h.get('id')
        if (h.get('net_bb', 0) < -25
                and hid not in cooler_ids_set
                and hid not in _allin_sd_ids):
            candidates['iii4_screening'].append(_hand_ctx(hid))
    # read-dependent screening (v7.60): result-INDEPENDENT verdict-flip pass.
    # Scans ALL HU river-call hands (won and lost) — the winning read-
    # dependent calls never reach the loss-anchored iii4_screening feed and
    # are exactly the ones that silently reinforce a -EV habit. The solver
    # runs each call's EV against a GTO-balanced range and a population
    # under-bluff band; a CALL/FOLD verdict that is not robust across the
    # band is surfaced for the analyst step to verdict.
    try:
        from gem_solver_integration import screen_read_dependent_calls, _SOLVER_AVAILABLE
        if _SOLVER_AVAILABLE:
            _bust_ids = {h['id'] for h in hands
                         if h.get('net_bb', 0) < -25 and h.get('id')}
            _rd_screen = screen_read_dependent_calls(
                hands=hands,
                hh_dir=SESSION_DIR,
                out_dir_base='/home/claude/solver_runs',
                session_tag=stats['volume']['date_range'],
                exclude_ids=_bust_ids,
            )
            for _item in _rd_screen:
                _ctx = _hand_ctx(_item['id'])
                _ctx['read_dependent_screen'] = _item['screen']
                candidates['read_dependent_screening'].append(_ctx)
        else:
            print("  read-dependent screener skipped: solver unavailable")
    except Exception as _rd_e:
        print(f"  read-dependent screener skipped: "
              f"{type(_rd_e).__name__}: {_rd_e}")
    # bestplay_screening (B151, Ron 2026-05-23): "Pokerbot's Picks" — Step 1
    # of the Pokerbot_Picks_Framework. The pipeline does STRUCTURAL filtering
    # only; it surfaces hands worth the analyst's attention. The analyst then
    # does Step 3 (archetype mapping) — a hand with NO archetype is NOT a
    # Pick. Result-agnostic: outcome / net_bb is never a screening criterion.
    #
    # Picks are RARE by design — the screen fires only on high-signal
    # STRUCTURAL markers, not on "got it in at low SPR" (which is most MTT
    # all-ins and carries no skill signal):
    #   (a) premium hand (QQ+/AK) in an ESCALATED pot (3BP/4BP/5BP) — a
    #       3-bet+ war already happened; catches the AA-reshove cascade.
    #   (b) a multi-street pressure line — triple-barrel, turn/river
    #       check-raise, or a river bluff-catch / river raise.
    #   (c) ICM phase (bubble / final-table) AND an escalated pot — the
    #       Macro/ICM-Leverage archetype feeder; bubble/FT alone is too
    #       broad, so it must be paired with real preflop escalation.
    # Low SPR is NOT a trigger — it is reported as context only when one of
    # the real triggers above already fired.
    def _is_premium(card_str):
        cs = (card_str or '')
        if len(cs) < 4:
            return False
        r1, r2 = cs[0], cs[2]
        if r1 == r2 and r1 in ('A', 'K', 'Q'):
            return True
        return {r1, r2} == {'A', 'K'}

    _bp_seen = set()
    for h in hands:
        hid = h.get('id')
        if not hid or hid in _bp_seen:
            continue
        # B166 (Ron 2026-05-24): a preflop fold is never a Pick — and skipping
        # it also avoids the parser's stray check_raises/hero_street_actions
        # on folded hands triggering a false candidate.
        if h.get('line') == 'fold_preflop' or h.get('pf_action') == 'fold':
            continue
        cards = ''.join(h.get('cards', []))
        pot_type = (h.get('pot_type', '') or '').upper()
        phase = (h.get('tournament_phase', '') or '').lower()
        spr = h.get('spr', None)
        escalated = pot_type in ('3BP', '4BP', '5BP')
        deep_escalated = pot_type in ('4BP', '5BP')
        # a hand only carries skill signal if Hero actually got it in or saw
        # a showdown — a 3-bet that folds the field, or a routine preflop
        # fold, is not a Pick. And sub-12BB is pure push/fold (no skill).
        contested = bool(h.get('pf_allin') or h.get('went_to_sd'))
        stack = h.get('stack_bb', 0) or 0
        reasons = []
        hsa = h.get('hero_street_actions', {}) or {}
        committed = h.get('hero_committed_bb', 0) or 0
        # (a) premium hand contested in a DEEP-escalated (4-bet+) pot — a
        # premium in a routine 3-bet pot is standard, not a Pick.
        if (_is_premium(cards) and deep_escalated and contested and stack >= 12):
            reasons.append(f'premium hand in {pot_type} pot')
        # (b) multi-street pressure / trapping lines
        if h.get('triple_barreled'):
            reasons.append('triple-barrel line')
        if h.get('double_barreled') and not h.get('triple_barreled'):
            reasons.append('double-barrel line')
        if h.get('check_raises'):
            reasons.append('check-raise (' +
                            ', '.join(str(x) for x in h.get('check_raises')) + ')')
        # (c) river aggression by Hero — great-bluff / great-value candidate
        # (a passive river call is not interesting; betting/raising is).
        if h.get('hero_bet_river') or h.get('raised_villain_bet_river'):
            reasons.append('river bet/raise by Hero')
        # (d) disciplined laydown — Hero folded on the turn or river facing a
        # bet AFTER investing >=10BB (a sick-fold candidate; routine flop-air
        # folds are excluded by the investment gate).
        _folded_late = ('fold' in str(hsa.get('turn', '')) or
                        'fold' in str(hsa.get('river', '')))
        if _folded_late and committed >= 10 and (
                h.get('folded_to_turn_barrel') or
                h.get('folded_to_villain_bet_river') or
                h.get('faced_turn_barrel') or h.get('faced_villain_bet_river')):
            reasons.append(f'laydown facing turn/river aggression '
                            f'(~{committed:.0f}BB invested)')
        # (e) preflop pressure decisions
        if h.get('is_squeeze'):
            reasons.append('preflop squeeze')
        if h.get('hero_called_3bet') or h.get('hero_called_4bet'):
            reasons.append('called a 3-bet/4-bet preflop')
        # (f) ICM-leverage phase paired with a 4-bet+ pot
        if (phase in ('bubble_zone', 'ft_zone') and deep_escalated
                and contested):
            reasons.append(f'ICM-leverage phase ({phase}) + {pot_type} pot')
        # (g) large contested pot reaching showdown / all-in — big pots carry
        # the most decision content regardless of how they escalated.
        if committed >= 30 and (contested or h.get('went_to_sd')):
            reasons.append(f'large contested pot (~{committed:.0f}BB committed)')
        if reasons:
            # low SPR is context, not a trigger — note it only alongside a hit
            if spr is not None and 0 < spr <= 1.5:
                reasons.append(f'context: low SPR ~{spr:.1f}')
            ctx = _hand_ctx(hid)
            ctx['bestplay_screen'] = {
                'reasons': reasons,
                'note': 'STRUCTURAL screen only — analyst assigns one of the '
                        '6 archetypes (Sick Call / Sick Fold / Great Value '
                        'Extraction / Great Bluff / Trap-Door Play / Macro-ICM '
                        'Leverage) or the hand is not a Pick. Result-agnostic.',
            }
            candidates['bestplay_screening'].append(ctx)
            _bp_seen.add(hid)

    # D3: Sort bestplay candidates — postflop multi-street lines first.
    # Preflop-only all-ins are less interesting as Picks.
    for _bp in candidates.get('bestplay_screening', []):
        _bp_h = hands_by_id.get(_bp.get('id'), {})
        _n_streets = sum(1 for st in ('flop', 'turn', 'river')
                         if (_bp_h.get('hero_street_actions', {}) or {}).get(st))
        _bp['_pick_priority'] = _n_streets * 10 + (1 if _bp_h.get('went_to_sd') else 0)
    candidates['bestplay_screening'].sort(
        key=lambda x: -x.get('_pick_priority', 0))

    # ---- v8.6.2: BIG RIVER CALL-DOWN DETECTOR ----
    # Surfaces river calls clearing a combined magnitude gate (>=40% pot AND
    # >=8BB AND eff_stack >=13BB). Result-agnostic — flags the decision, not
    # the outcome. De-dupes with existing D2/bust/all-in buckets.
    RIVER_CALLDOWN_MIN_BB = 8
    RIVER_CALLDOWN_MIN_POT_FRAC = 0.40
    RIVER_CALLDOWN_MIN_EFF_BB = 13
    _existing_ids = set()
    for _bk in ('bust_audit', 'coolers', 'mistakes', 'punts'):
        for _c in candidates.get(_bk, []):
            _existing_ids.add(_c.get('id', ''))
    for h in hands:
        if not h.get('vpip') or not h.get('id'):
            continue
        _eff = h.get('eff_stack_bb') or h.get('stack_bb') or 0
        if _eff < RIVER_CALLDOWN_MIN_EFF_BB:
            continue
        # Check if Hero called on the river
        _river_action = (h.get('hero_street_actions', {}) or {}).get('river', '')
        if 'call' not in str(_river_action).lower():
            continue
        # Get call amount from action ledger
        _call_bb = 0
        _pot_faced = 0
        for _a in (h.get('action_ledger') or []):
            if _a.get('street') == 'river':
                if _a.get('player') == h.get('hero') and _a.get('action') == 'calls':
                    _call_bb = _a.get('amount_bb', 0) or 0
                elif _a.get('player') != h.get('hero') and _a.get('action') in ('bets', 'raises'):
                    _pot_faced = _a.get('pot_before_bb', 0) or 0
        if _call_bb < RIVER_CALLDOWN_MIN_BB:
            continue
        _pot_frac = _call_bb / max(_pot_faced, 1) if _pot_faced > 0 else 0
        if _pot_frac < RIVER_CALLDOWN_MIN_POT_FRAC:
            continue
        _req_eq = _call_bb / (_pot_faced + _call_bb) * 100 if (_pot_faced + _call_bb) > 0 else 50
        _dup = h['id'] in _existing_ids
        _ctx = _hand_ctx(h['id'])
        _ctx['river_call_bb'] = round(_call_bb, 1)
        _ctx['pot_faced_bb'] = round(_pot_faced, 1)
        _ctx['required_equity_pct'] = round(_req_eq, 1)
        _ctx['pot_fraction'] = round(_pot_frac * 100, 1)
        if _dup:
            _ctx['dup_of'] = 'existing_bucket'
        candidates['big_river_calldowns'].append(_ctx)
    _n_brc = len(candidates['big_river_calldowns'])
    _n_brc_new = sum(1 for c in candidates['big_river_calldowns'] if 'dup_of' not in c)
    if _n_brc:
        print(f"  Big river call-downs: {_n_brc} flagged ({_n_brc_new} new, "
              f"{_n_brc - _n_brc_new} dup with existing buckets)")

    # Pot-odds & equity enrichment (Ron 2026-05-26): attach a `pot_odds` block
    # to every candidate that is an all-in call so the analyst argument can
    # carry the §3b arithmetic (price -> required equity, Hero's equity, EV)
    # instead of asserting it. Wrapped — enrichment must never break the
    # candidate file.
    try:
        from gem_pot_odds import enrich_candidates as _enrich_pot_odds
        _po_stats = _enrich_pot_odds(candidates, hands, SESSION_DIR)
        print(f"  pot-odds enrichment: {_po_stats.get('enriched', 0)} hands "
              f"enriched, {_po_stats.get('integrity_flags', 0)} integrity "
              f"flag(s), {_po_stats.get('skipped', 0)} skipped"
              + (f" — {_po_stats['note']}" if _po_stats.get('note') else ""))
    except Exception as _po_e:
        print(f"  pot-odds enrichment skipped: "
              f"{type(_po_e).__name__}: {_po_e}")

    # BUG-12 (Ron review 2026-05-31): thread pot_odds into report_data so
    # the hand detail renderer can surface the bounty-adjusted math.
    # Collect pot_odds blocks from enriched candidates into a dict by hand id.
    _po_by_id = {}
    for _bk in ('bust_audit', 'coolers', 'mistakes', 'punts',
                'iii4_screening', 'read_dependent_screening', 'bestplay_screening'):
        for _ctx in candidates.get(_bk, []) or []:
            if isinstance(_ctx, dict) and _ctx.get('pot_odds') and _ctx.get('id'):
                _po_by_id[_ctx['id']] = _ctx['pot_odds']
    if _po_by_id:
        report_data['pot_odds_by_hand'] = _po_by_id
        # v8.12.0: migration-audit verdict columns need this equity — the
        # initial pko_research pass ran before this stage existed in rd.
        try:
            from gem_pko_research import refresh_migration_equity
            refresh_migration_equity(report_data)
        except Exception:
            pass

    # B256: emit blindspot_sample into candidates so the analyst can see
    # the full coverage-gate worklist BEFORE writing, not after failing.
    _bs_cand = stats.get('blindspot_audit', {})
    if isinstance(_bs_cand, dict):
        candidates['blindspot_sample'] = _bs_cand.get('sampled', [])
    else:
        candidates['blindspot_sample'] = []

    # B-V10: ALL all-in hands must be in the candidate pool for analyst review.
    # Every all-in is a critical decision — the analyst must verdict each one.
    _existing_cand_ids = set()
    for _bk in candidates.values():
        if isinstance(_bk, list):
            for _c in _bk:
                if isinstance(_c, dict) and _c.get('id'):
                    _existing_cand_ids.add(_c['id'])
    _eai_all = stats.get('eai', {}).get('hands', []) or []
    _allin_candidates = []
    for _e in _eai_all:
        _eid = _e.get('id', '')
        if _eid and _eid not in _existing_cand_ids:
            _allin_candidates.append(_hand_ctx(_eid))
            _existing_cand_ids.add(_eid)
    candidates['all_in_review'] = _allin_candidates

    # ---- EFFICIENCY #1: PRE-FILLED VERDICTS ----
    # Auto-generate suggested verdicts for ~60% of candidates so the analyst
    # starts from a filled template instead of blank. The analyst confirms/
    # overrides. Cuts analyst time by ~40-50%.
    # _eai_by_id_pf already built above (before _hand_ctx)
    _agg_block = report_data.get('aggression_analysis', {}) or {}
    _agg_by_id = {}
    for _bk_agg in ('missed_aggression', 'ambiguous', 'correctly_passive',
                     'correctly_aggressive', 'too_aggressive', 'ambiguous_aggressive'):
        for _c in (_agg_block.get(_bk_agg) or []):
            _agg_by_id[_c.get('hand_id', '')] = _c

    def _to_chart_notation(cards_str):
        """Convert 'AhKd' → 'AKo', 'AsKs' → 'AKs', 'JdJc' → 'JJ'.

        v8.12.8 QA3: ranks MUST be high-first — '8hAd' rendered as '8Ao'
        and, worse, FAILED every chart-membership test ('8Ao' is never in
        a range set), silently flipping IN-range hands to OUTSIDE for any
        low-card-first deal."""
        cs = cards_str.replace(' ', '')
        if len(cs) != 4:
            return cards_str
        r0, s0, r1, s1 = cs[0], cs[1], cs[2], cs[3]
        if r0 == r1:
            return f'{r0}{r1}'  # pocket pair
        _rv = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8,
               '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
        if _rv.get(r1, 0) > _rv.get(r0, 0):
            r0, r1 = r1, r0
        return f'{r0}{r1}{"s" if s0 == s1 else "o"}'

    def _compute_decision_math(h, ctx):
        """SPEC #3: Per-street pot-odds + equity for candidate hands.
        Returns dict with key_decision_street and per-street blocks."""
        ledger = h.get('action_ledger', [])
        hero = h.get('hero', 'Hero')
        bb = h.get('bb_blind', 1) or 1
        board = h.get('board', [])
        hero_cards = h.get('cards', [])
        villains = h.get('villains', {})
        pf_allin = h.get('pf_allin')

        result = {'streets': {}, 'key_decision_street': 'preflop'}
        # Track pot per street
        pot = 0
        committed_by_player = {}
        _last_hero_street = 'preflop'

        for street in ('preflop', 'flop', 'turn', 'river'):
            st_actions = [a for a in ledger if a.get('street') == street]
            if not st_actions:
                continue
            hero_acted = False
            _hero_action = None
            _villain_bet_bb = 0
            _pot_before_villain_bet = pot
            _hero_call_amount = 0

            for a in st_actions:
                player = a.get('player', '')
                action = a.get('action', '')
                amt = a.get('amount_bb', 0) or 0

                if action in ('raises', 'bets') and player != hero:
                    _pot_before_villain_bet = pot
                    _villain_bet_bb = amt
                    pot += amt
                elif action == 'calls' and player == hero:
                    hero_acted = True
                    _hero_action = 'call'
                    _hero_call_amount = amt
                    _last_hero_street = street
                    pot += amt
                elif action == 'raises' and player == hero:
                    hero_acted = True
                    _hero_action = 'raise'
                    _hero_call_amount = amt
                    _last_hero_street = street
                    pot += amt
                elif action in ('raises', 'bets') and player == hero:
                    hero_acted = True
                    _hero_action = 'bet'
                    _last_hero_street = street
                    pot += amt
                elif action == 'calls':
                    pot += amt
                elif action == 'posts':
                    pot += amt
                elif action == 'folds' and player == hero:
                    hero_acted = True
                    _hero_action = 'fold'
                    _last_hero_street = street

            if hero_acted and _hero_action in ('call', 'fold') and _hero_call_amount > 0:
                _pot_facing = _pot_before_villain_bet + _villain_bet_bb
                _final_pot = _pot_facing + _hero_call_amount
                _req_eq = _hero_call_amount / _final_pot if _final_pot > 0 else 0

                # Equity computation
                _eq = None
                _eq_method = 'none'
                _range_desc = ''
                _range_source = 'default_population'
                _range_confidence = 'low'

                # Check for shown cards (exact equity)
                _primary_v = h.get('primary_villain', {}).get('name', '')
                _v_shown = None
                if _primary_v and _primary_v in villains:
                    _v_shown = villains[_primary_v].get('shown_cards')
                if _v_shown and hero_cards and len(hero_cards) >= 2:
                    # Exact equity vs shown cards
                    try:
                        _board_at_street = board[:3] if street == 'flop' else (
                            board[:4] if street == 'turn' else board[:5])
                        if street == 'preflop':
                            _board_at_street = []
                        import gem_eai_equity
                        _eq_result = gem_eai_equity.equity(
                            hero_cards, [_v_shown], _board_at_street)
                        if _eq_result:
                            _eq = _eq_result.get('hero_equity')
                            _eq_method = 'exact_vs_shown_cards'
                            _range_desc = f"villain's shown {_to_chart_notation(''.join(_v_shown))}"
                            _range_source = 'shown_cards_exact'
                            _range_confidence = 'high'
                    except Exception:
                        pass

                # Fallback: use EAI equity if available
                if _eq is None:
                    _eai_h = _eai_by_id_pf.get(h.get('id', ''))
                    if _eai_h and _eai_h.get('hero_equity') is not None:
                        _eq = _eai_h['hero_equity']
                        _eq_method = 'eai_at_allin'
                        _range_source = 'action_pattern_inferred'
                        _range_confidence = 'medium'

                _ev = None
                if _eq is not None:
                    _ev = _eq * _final_pot - _hero_call_amount

                result['streets'][street] = {
                    'hero_action': _hero_action,
                    'board': ' '.join(board[:{'preflop': 0, 'flop': 3, 'turn': 4, 'river': 5}[street]]),
                    'pot_before_villain_bet_bb': round(_pot_before_villain_bet, 1),
                    'villain_bet_bb': round(_villain_bet_bb, 1),
                    'pot_facing_hero_bb': round(_pot_facing, 1),
                    'hero_call_amount_bb': round(_hero_call_amount, 1),
                    'final_pot_if_call_bb': round(_final_pot, 1),
                    'required_equity': round(_req_eq, 3),
                    'hero_equity_vs_range': round(_eq, 3) if _eq is not None else None,
                    'equity_method': _eq_method,
                    'ev_call_bb': round(_ev, 1) if _ev is not None else None,
                    'villain_range': {
                        'desc': _range_desc,
                        'source': _range_source,
                        'confidence': _range_confidence,
                    },
                }

        result['key_decision_street'] = _last_hero_street
        # Verdict direction
        _key_st = result['streets'].get(_last_hero_street, {})
        _ev_key = _key_st.get('ev_call_bb')
        if pf_allin and _key_st.get('hero_action') in ('call', 'raise'):
            if _ev_key is not None:
                result['verdict_direction'] = '+EV call' if _ev_key >= 0 else '-EV call'
            else:
                result['verdict_direction'] = 'unknown'
        elif _key_st.get('hero_action') == 'fold':
            result['verdict_direction'] = 'correct fold (review earlier action)'
        elif _key_st.get('hero_action') == 'call':
            if _ev_key is not None:
                result['verdict_direction'] = '+EV call' if _ev_key >= 0 else '-EV call'
            else:
                result['verdict_direction'] = 'unknown'
        else:
            result['verdict_direction'] = 'unknown'

        return result

    # ---- AUTO-VERDICT HELPERS (v8.3.0) ----
    _NOISE_FLOOR_BB = 0.20
    _FLIP_LO, _FLIP_HI = 0.40, 0.60
    _CALL_PRICED_EQ = 0.45
    _PUSH_DEPTH_MAX = 25   # v8.9.0 BUG-2: extended from 15BB with GTOW ChipEV range coverage
    _STEAL_DEPTH_MAX = 15  # R1 missed-steal gate (pure push/fold depth; unchanged)
    _POS_ALIAS = {'UTG': ['LJ'], 'EP': ['LJ'], 'LJ': ['UTG'],
                  'MP': ['HJ'], 'UTG+1': ['HJ', 'LJ'], 'UTG+2': ['HJ', 'MP']}

    def _hero_role(h):
        """Classify Hero's preflop role in an all-in pot.

        v8.4.0: check action_ledger to determine if Hero was the aggressor.
        Fixes A2o SB open-jam misclassified as caller_vs_jam.
        """
        pa = h.get('pf_action', '')
        # Check if Hero's own action was all-in (aggressor, not caller)
        _hero_jammed = False
        for _a in (h.get('action_ledger') or []):
            if (_a.get('player') == h.get('hero')
                    and _a.get('street') == 'preflop'
                    and _a.get('is_all_in')
                    and _a.get('action') in ('raises', 'bets')):
                _hero_jammed = True
                break
        # If Hero jammed first-in, it's an open-shove regardless of villain_jammed
        if _hero_jammed and h.get('first_in'):
            return 'open_shove'
        if _hero_jammed and (pa == '3bet' or h.get('hero_3bet')):
            return 'threebet_jam'
        if h.get('villain_jammed') and pa in ('call', '3bet') and not h.get('first_in') and not _hero_jammed:
            return 'caller_vs_jam'
        if pa == 'call':
            return 'caller'
        if pa == '3bet' or h.get('hero_3bet'):
            return 'threebet_jam'
        if pa in ('raise', 'jam') and h.get('first_in'):
            return 'open_shove'
        if pa == 'fold':
            return 'folder'
        return 'other'

    def _allin_equity_with_fallback(h, eai_entry):
        """Get all-in equity, falling back to matchups when eai is null."""
        eq = (eai_entry or {}).get('hero_equity')
        if eq is not None:
            return eq
        # Fallback: compute from known showdown cards
        mm = h.get('matchups') or {}
        if mm and h.get('went_to_sd'):
            try:
                from phevaluator import evaluate_cards
                hero_cards = h.get('cards', [])
                board = h.get('board', [])
                if hero_cards and board and len(board) >= 5:
                    # Simple equity estimation vs shown villain cards
                    for _vid, _vm in mm.items():
                        v_cards = _vm.get('villain_cards', [])
                        if v_cards and len(v_cards) >= 2:
                            h_rank = evaluate_cards(*hero_cards, *board[:5])
                            v_rank = evaluate_cards(*v_cards, *board[:5])
                            # Lower rank = better hand in phevaluator
                            return 0.0 if h_rank > v_rank else (0.5 if h_rank == v_rank else 1.0)
            except Exception:
                pass
        return None

    def _prefill_verdict(ctx, bucket):
        """Generate a suggested verdict + argument for one candidate hand.

        v8.3.0: Role-aware preflop rules (R0-R14) from auto-verdict spec.
        Distinguishes open-shove vs 3bet-jam vs caller-of-jam.
        """
        hid = ctx.get('id', '')
        h = hands_by_id.get(hid, {})
        eai = _eai_by_id_pf.get(hid)
        _voc_raw = _variance_outcomes.get(hid)
        voc = _voc_raw['outcome'] if isinstance(_voc_raw, dict) else _voc_raw
        agg = _agg_by_id.get(hid)
        pf_allin = h.get('pf_allin') or ctx.get('pf_allin')
        net = h.get('net_bb') or ctx.get('net_bb', 0)
        dp = ctx.get('draw_profiles', {})

        # Build context strings for draft arguments
        _cards_raw = ctx.get('cards', '') or ''.join(h.get('cards', []))
        _cards = _to_chart_notation(_cards_raw)
        _pos = h.get('position') or ctx.get('position', '?')

        # ALL-IN EQUITY LINE — ALWAYS include when available
        _equity_line = ''
        if eai and eai.get('hero_equity') is not None:
            _ai_eq = eai['hero_equity']
            _ai_pct = _ai_eq * 100 if _ai_eq <= 1.5 else _ai_eq
            _ai_fav = 'favorite' if eai.get('is_favorite') else 'underdog'
            _ai_n = eai.get('n_allin', 2)
            # v8.12.8 QA3 (66133234): "(3-way)" read as if Hero KNEW it was
            # 3-way when acting — the field formed by showdown; say so.
            _ai_mw = (f' ({_ai_n}-way by showdown — decision may have faced '
                      'fewer)' if _ai_n > 2 else '')
            # v8.12.9 policy (auto-verdict handoff §1.2): revealed-hand
            # equity is LUCK context — never the decision basis (that is
            # range equity's job).
            _equity_line = (f'\n- All-in result equity: **{_ai_pct:.0f}%** '
                            f'({_ai_fav}{_ai_mw}) — luck/result context, '
                            'not the decision basis')
        # P3b: ALWAYS use effective stack at decision, not nominal. Nominal
        # over-estimates depth in many-way pots and vs short-effective opponents,
        # leading to wrong cooler/read-dependent classification (91 hands affected
        # in lanks662 session). Fallback chain: eff_at_decision → eff → nominal.
        _stack = (h.get('eff_stack_bb_at_decision')
                  or ctx.get('eff_stack_at_decision_bb')
                  or h.get('eff_stack_bb')
                  or h.get('stack_bb')
                  or ctx.get('stack_bb', 0))
        _act = ctx.get('action_summary', '') or h.get('action_summary', '')
        _dp_str = ' → '.join(f"{st}: {v}" for st, v in dp.items() if v) if dp else ''

        # ---- PUSH RANGE CITATION (systematic) ----
        # Only fires when Hero OPEN-SHOVED (not called someone else's jam).
        # Check action ledger for Hero's preflop raise/bet that is all-in.
        # v8.9.0 BUG-2: extended to _PUSH_DEPTH_MAX (25BB), added JAM_ chart
        # search + position aliasing + depth-tiered quantization.
        _push_range_note = ''
        _hero_open_jammed = False
        _in_push = None   # v8.9.0: range membership for R2 verdict gating
        if pf_allin and _stack <= _PUSH_DEPTH_MAX and h.get('first_in'):
            for _pfa_c in (h.get('action_ledger') or []):
                if (_pfa_c.get('player') == h.get('hero')
                        and _pfa_c.get('street') == 'preflop'
                        and _pfa_c.get('action') in ('raises', 'bets')
                        and _pfa_c.get('is_all_in')):
                    _hero_open_jammed = True
                    break
        if _hero_open_jammed:
            # v8.9.0: quantize stack to nearest chart depth tier
            _pos_tries = [_pos] + _POS_ALIAS.get(_pos, [])
            if _stack <= 9: _target_depth = 8
            elif _stack <= 11: _target_depth = 10
            elif _stack <= 13.5: _target_depth = 12
            elif _stack <= 17.5: _target_depth = 15
            elif _stack <= 22.5: _target_depth = 20
            else: _target_depth = 25
            # Prefer JAM_ chart (exact jam subset) over PUSH_ (full open range)
            _push_key = None
            for _px in ('JAM_', 'PUSH_'):
                for _pp in _pos_tries:
                    _ck = f'{_px}{_target_depth}BB_{_pp}'
                    if (ranges or {}).get(_ck):
                        _push_key = _ck
                        break
                if _push_key:
                    break
            # Fallback: try adjacent depth tiers for same position
            if not _push_key:
                _adj_tiers = [8, 10, 12, 15, 20, 25]
                _adj_tiers.sort(key=lambda d: abs(d - _target_depth))
                for _at in _adj_tiers[1:3]:  # nearest 2 alternatives
                    for _px in ('JAM_', 'PUSH_'):
                        for _pp in _pos_tries:
                            _ck = f'{_px}{_at}BB_{_pp}'
                            if (ranges or {}).get(_ck):
                                _push_key = _ck
                                break
                        if _push_key:
                            break
                    if _push_key:
                        break
            try:
                _push_hands = (ranges or {}).get(_push_key or '', {})
                if _push_hands:
                    _in_push = _cards in _push_hands
                    _n_combos = len(_push_hands)
                    # Build human-readable top + boundary
                    _sorted_push = sorted(_push_hands.keys(),
                        key=lambda x: (-({'A':14,'K':13,'Q':12,'J':11,'T':10,
                                          '9':9,'8':8,'7':7,'6':6,'5':5,'4':4,
                                          '3':3,'2':2}.get(x[0],0)),
                                        -({'A':14,'K':13,'Q':12,'J':11,'T':10,
                                          '9':9,'8':8,'7':7,'6':6,'5':5,'4':4,
                                          '3':3,'2':2}.get(x[1] if len(x)>1 else '2',0))))
                    _top5 = ', '.join(_sorted_push[:5])
                    _bot3 = ', '.join(_sorted_push[-3:])
                    _push_range_note = (
                        f'\n\n### PUSH RANGE ({_pos} {_stack:.0f}BB → {chart_display_label(_push_key)})\n'
                        f'- Chart: {chart_display_label(_push_key)} ({_n_combos} hand classes)\n'
                        f'- Top: {_top5}...\n'
                        f'- Boundary: ...{_bot3}\n'
                        f'- **{_cards}: {"IN range ✓" if _in_push else "OUTSIDE range ✗"}**'
                    )
                else:
                    # No chart found for this position — check if depth tier
                    # has charts for OTHER positions (→ this position never jams)
                    _any_at_tier = any(
                        k.startswith(f'JAM_{_target_depth}BB_') or
                        k.startswith(f'PUSH_{_target_depth}BB_')
                        for k in (ranges or {}))
                    if _any_at_tier:
                        _in_push = False  # position has no GTO jam range at this depth
                        _push_range_note = (
                            f'\n\n### PUSH RANGE ({_pos} {_stack:.0f}BB)\n'
                            f'- **No GTO jam range for {_pos} at {_target_depth}BB** '
                            f'(solver uses open-raise only). Open-jam is non-standard.'
                        )
            except Exception:
                pass

        # B161: Villain push range citation when Hero FACES a jam
        # v8.9.0 BUG-2: extended to _PUSH_DEPTH_MAX, added JAM_ search + aliases
        _villain_push_note = ''
        if pf_allin and _stack <= _PUSH_DEPTH_MAX and not _hero_open_jammed and h.get('villain_jammed'):
            _jammer_pos = h.get('opener_position', '')
            if _jammer_pos:
                _vpos_tries = [_jammer_pos] + _POS_ALIAS.get(_jammer_pos, [])
                _avail_vdepths = []
                for _rk in (ranges or {}):
                    if _rk.startswith(('PUSH_', 'JAM_')):
                        for _vp in _vpos_tries:
                            if _rk.endswith(f'_{_vp}'):
                                try:
                                    _vd = int(re.search(r'(\d+)BB', _rk).group(1))
                                    _avail_vdepths.append((_vd, _rk))
                                except Exception:
                                    pass
                if _avail_vdepths:
                    _avail_vdepths.sort(key=lambda x: abs(x[0] - _stack))
                    _vpush_key = _avail_vdepths[0][1]
                    _vpush_rng = (ranges or {}).get(_vpush_key, set())
                    if _vpush_rng:
                        _vn_combos = len(_vpush_rng)
                        _vtop5 = ', '.join(sorted(list(_vpush_rng))[:5])
                        _villain_push_note = (
                            f'\n- Villain ({_jammer_pos}) push range: '
                            f'{chart_display_label(_vpush_key)} ({_vn_combos} hand classes)'
                            f'\n- Top: {_vtop5}...')

        # REJAM range citation: when Hero rejammed (3-bet jam), cite the REJAM chart
        _rejam_note = ''
        _in_rj = None  # v8.8.9 BUG-6: track rejam range membership for R4 verdict gating
        # v8.14.1 REV5 (72692569): resolve re-jam membership at ANY depth. The
        # old `_stack <= 30` gate let a 62BB 3-bet jam fall through to `_in_rj is
        # None` -> "no rejam chart for this matchup", contradicting the canonical
        # Range-evidence block (which resolved REJAM_MPvsUTG1, AA INSIDE). The
        # _hero_role == 'threebet_jam' check already restricts this to re-jams.
        # v8.17.1 Iteration 1 corrective: a "raise" over a villain who is ALREADY
        # all-in is a CALL-OFF of that jam (call_vs_jam), never a re-jam — the
        # canonical action kind owns this, so a call-off (83915520) never cites a
        # re-jam chart / renders a re-jam verdict.
        from gem_decision_snapshot import hero_action_kind as _ds_canon_akind
        _canon_akind = _ds_canon_akind(h)
        if (pf_allin and _hero_role(h) == 'threebet_jam'
                and _canon_akind not in ('call_vs_jam', 'call_off')):
            _opener = h.get('opener_position', '')
            if _opener and _pos:
                # v8.14.1 REV5: strip '+' to match gem_ranges.build_range_evidence
                # (REJAM_MPvsUTG1, not REJAM_MPvsUTG+1) — the single canonical key,
                # so coverage-builder membership can never disagree on chart
                # EXISTENCE with the rendered Range-evidence block.
                _rj_key = f'REJAM_{_pos.replace("+", "")}vs{_opener.replace("+", "")}'
                _rj_rng = (ranges or {}).get(_rj_key, set())
                if _rj_rng:
                    _rj_n = len(_rj_rng)
                    _in_rj = _cards in _rj_rng if _cards else False
                    _rj_status = 'IN range' if _in_rj else 'OUTSIDE range'
                    # v8.12.8 QA3 (Ron: "REJAM_SBvsHJ means nothing"):
                    # human label + the actual range, not just a file key.
                    _rv_rj = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6,
                              '7': 7, '8': 8, '9': 9, 'T': 10, 'J': 11,
                              'Q': 12, 'K': 13, 'A': 14}
                    _rj_sorted = sorted(
                        _rj_rng,
                        key=lambda x: (-_rv_rj.get(x[0], 0),
                                       -_rv_rj.get(x[1] if len(x) > 1
                                                   else '2', 0)))
                    _rejam_note = (
                        f'\n- Hero rejam range — {_pos} 3-bet jam over a '
                        f'{_opener} open ({_rj_n} hand classes)'
                        f'\n- Top: {", ".join(_rj_sorted[:5])}...'
                        f'\n- Boundary: ...{", ".join(_rj_sorted[-3:])}'
                        f'\n- **{_cards}: {_rj_status}**')

        # SPEC #4: Build §3b argument from decision math when available
        _dm = ctx.get('decision_math', {})
        _key_st = _dm.get('key_decision_street', 'preflop')
        _st_data = _dm.get('streets', {}).get(_key_st, {})
        _has_math = bool(_st_data and _st_data.get('required_equity'))

        def _build_math_argument(tldr, verdict_code):
            """Build a full §3b argument from decision math."""
            parts = [f'**TL;DR:** {tldr}']
            if _has_math:
                _req = _st_data.get('required_equity', 0)
                _heq = _st_data.get('hero_equity_vs_range')
                _ev = _st_data.get('ev_call_bb')
                _pot_f = _st_data.get('pot_facing_hero_bb', 0)
                _call = _st_data.get('hero_call_amount_bb', 0)
                _final = _st_data.get('final_pot_if_call_bb', 0)
                _vr = _st_data.get('villain_range', {})
                _vrd = _vr.get('desc', '')
                _vrc = _vr.get('confidence', 'low')
                _em = _st_data.get('equity_method', '')

                parts.append('')
                parts.append(f'### PRICE → REQUIRED EQUITY')
                # v8.12.8 QA3 (66796475: 39.2% here vs 43.3% in the
                # pot-odds block): the ledger-walk pot reconstruction can
                # over-count raise increments. When the pot-odds engine
                # (GG's authoritative Total-pot line) computed this hand,
                # its figures WIN — one number, one source.
                _po_auth = ctx.get('pot_odds') or {}
                if _po_auth.get('mode') == 'street_calls':
                    _po_auth = next(
                        (ps for ps in _po_auth.get('per_street_calls', [])
                         if ps.get('street') == _key_st), {})
                if (_po_auth.get('required_eq_pct') is not None
                        and _po_auth.get('call_bb') is not None):
                    _req = _po_auth['required_eq_pct'] / 100.0
                    _call = _po_auth['call_bb']
                    _pot_f = _po_auth.get('pot_before_call_bb', _pot_f)
                parts.append(f'- Call {_call:.1f}BB into {_pot_f:.1f}BB pot → '
                             f'need **{_req*100:.1f}%**')
                if _heq is not None:
                    _eq_pct = _heq * 100 if _heq <= 1.5 else _heq
                    if _vrd:
                        if _em == 'exact_vs_shown_cards':
                            parts.append(f'- {_cards} vs {_vrd} → **{_eq_pct:.0f}%**')
                        else:
                            parts.append(f'- {_cards} vs {_vrd} → '
                                         f'**~{_eq_pct:.0f}%** ({_vrc})')
                    else:
                        parts.append(f'- Hero equity: **~{_eq_pct:.0f}%**')
                if _ev is not None:
                    parts.append(f'- EV of call: **{_ev:+.1f} BB**')
            # Always include all-in equity when available
            if _equity_line:
                parts.append(_equity_line)
            # Append push range citation if applicable (systematic)
            if _push_range_note:
                parts.append(_push_range_note)
            if _villain_push_note:
                parts.append(_villain_push_note)
            if _rejam_note:
                parts.append(_rejam_note)
            return '\n'.join(parts)

        # ================================================================
        # AUTO-VERDICT RULES (v8.3.0) — role-aware, run BEFORE bucket logic
        # ================================================================
        _role = _hero_role(h)
        _eq_av = _allin_equity_with_fallback(h, eai)
        _flag = ctx.get('mistake_type', '') or ctx.get('flag', '')

        # R0: Noise-suppress marginal missed steals below EV floor
        if 'marginal' in _flag.lower() and 'steal' in _flag.lower():
            if abs(net) < _NOISE_FLOOR_BB:
                return {'verdict': 'SUPPRESS', 'confidence': 'HIGH',
                        'auto_rule': 'R0_noise',
                        'argument': 'Sub-0.2BB missed steal — suppressed below EV noise floor.'}

        # R1: Clear missed steal — CO/BTN fold inside open range, no ICM
        # v8.7.1 FIX: require first-in AND non-shove depth (>15BB).
        # Without this, SB/BB folds facing raises at short stacks get
        # mis-flagged as III.2 Mistake (handover bug C, hand 43414176).
        if 'clear' in _flag.lower() and 'steal' in _flag.lower():
            _phase = h.get('tournament_phase', '')
            _ic = h.get('icm_context') or {}
            if not h.get('first_in'):
                return {'verdict': '', 'confidence': 'LOW',
                        'auto_rule': 'R1_steal_gate_failed',
                        'argument': f'Clear steal flag but Hero was not first-in. '
                                    f'Route to analyst screening.'}
            if _stack <= _STEAL_DEPTH_MAX:  # v8.9.0: R1 uses steal gate, not push depth
                return {'verdict': '', 'confidence': 'LOW',
                        'auto_rule': 'R1_steal_gate_failed',
                        'argument': f'Clear steal flag but stack {_stack:.1f}BB is push/fold '
                                    f'depth. Route to analyst screening.'}
            if _phase not in ('bubble_zone', 'final_table') and not _ic.get('near_bubble'):
                return {'verdict': 'III.2 Mistake', 'confidence': 'HIGH',
                        'auto_rule': 'R1_missed_steal_clear',
                        'argument': _build_math_argument(
                            f'Folded {_cards} first-in from {_pos} — inside the '
                            f'position open range, no ICM override. Clear missed steal.',
                            'III.2')}

        # R-structural: pair-over-pair cooler (fires even when equity is None)
        if pf_allin and h.get('went_to_sd') and net < 0 and _stack <= _PUSH_DEPTH_MAX:
            _hero_cards = _cards.strip()
            _v_cards = ''
            for _mm in (h.get('matchups') or {}).values():
                _v_cards = _mm.get('villain_hand_class', '') or ''
                if _v_cards: break
            if not _v_cards:
                _shows = h.get('showdown_reveals') or {}
                for _sv in _shows.values():
                    if isinstance(_sv, dict) and not _sv.get('is_hero'):
                        _v_cards = _sv.get('hand_class', '') or ''
                        if _v_cards: break
            if (len(_hero_cards) == 2 and _hero_cards[0] == _hero_cards[1]
                    and len(_v_cards) >= 2 and _v_cards[0] == _v_cards[1]):
                _hr = 'AKQJT98765432'.index(_hero_cards[0]) if _hero_cards[0] in 'AKQJT98765432' else 99
                _vr = 'AKQJT98765432'.index(_v_cards[0]) if _v_cards[0] in 'AKQJT98765432' else 99
                if _hr > _vr:
                    return {'verdict': 'I.7 Cooler', 'confidence': 'HIGH',
                            'auto_rule': 'R_structural_pair_over_pair',
                            'argument': _build_math_argument(
                                f'{_hero_cards} vs {_v_cards} — pair-over-pair at {_stack:.0f}BB. '
                                f'Structural cooler, no fold possible.', 'I.7')}

        # Preflop all-in rules (R2-R6) — role-aware
        if pf_allin and h.get('went_to_sd') and _eq_av is not None:
            # R2: Open-shove range-gated verdict (v8.9.0 BUG-2)
            # v8.4.3: branch on SD result — correct push lost to dominator = I.7
            # v8.9.0: _in_push gates the verdict. Out-of-range → III.4.
            if _role == 'open_shove' and _stack <= _PUSH_DEPTH_MAX:
                # Gate: if definitively outside push range, route to III.4
                if _in_push is not None and not _in_push:
                    _won_r2 = net >= 0
                    _r2_outcome = 'won despite non-standard shove' if _won_r2 else 'lost with non-standard shove'
                    return {'verdict': 'III.4 Read-dependent', 'outcome': _r2_outcome,
                            'confidence': 'MEDIUM', 'auto_rule': 'R2_open_shove_out_of_range',
                            'argument': _build_math_argument(
                                f'Open-shove {_cards} from {_pos} at {_stack:.0f}BB — '
                                f'outside standard jam range '
                                f'({_eq_av*100:.0f}% equity). '
                                f'Needs read/population confirmation.',
                                'III.4')}
                # In-range or unknown: existing logic
                if net < 0 and _eq_av is not None and _eq_av < 0.35:
                    # v8.6.0: only I.7 for structural pair-over-pair. Non-pair
                    # shoves into a dominator are III.5 (standard push, variance).
                    _r2_structural = False
                    _r2_hero_pair = len(_cards) == 2 and _cards[0] == _cards[1]
                    if _r2_hero_pair:
                        for _mm in (h.get('matchups') or {}).values():
                            _vc = _mm.get('villain_hand_class', '') or ''
                            if len(_vc) >= 2 and _vc[0] == _vc[1]:
                                _vr = 'AKQJT98765432'.index(_vc[0]) if _vc[0] in 'AKQJT98765432' else 99
                                _hr = 'AKQJT98765432'.index(_cards[0]) if _cards[0] in 'AKQJT98765432' else 99
                                if _hr > _vr:
                                    _r2_structural = True
                                    break
                    if _r2_structural:
                        return {'verdict': 'I.7 Cooler', 'outcome': 'push_into_dominator',
                                'confidence': 'HIGH', 'auto_rule': 'R2_open_shove_cooler',
                                'argument': _build_math_argument(
                                    f'Correct open-shove ({_cards} {_pos} {_stack:.0f}BB) '
                                    f'— pair-over-pair ({_eq_av*100:.0f}% equity). Structural cooler.',
                                    'I.7')}
                    else:
                        return {'verdict': 'III.5 Justified', 'outcome': 'push_into_dominator',
                                'confidence': 'HIGH', 'auto_rule': 'R2_open_shove_dominated',
                                'argument': _build_math_argument(
                                    f'Open-shove ({_cards} {_pos} {_stack:.0f}BB) '
                                    f'inside push range, ran into top of calling range '
                                    f'({_eq_av*100:.0f}% equity). Standard push, lost to variance.',
                                    'III.5')}
                # v8.13.1 P1 (verdict-contradiction): only assert chart
                # membership when it was actually resolved. When _in_push is
                # None the engine could not place the hand in a push chart, so
                # the auto TL;DR must NOT claim "inside the push range" — that
                # false claim is what contradicted the hand-grid push widget on
                # 2026-06-13 (KJo UTG+1: TL;DR "inside push range / standard"
                # vs widget "outside PUSH_10BB_UTG+1").
                if _in_push is True:
                    _r2_push_arg = (
                        f'Short-stack open-shove ({_cards} {_pos} {_stack:.0f}BB) '
                        f'inside the push range — standard, result is variance.')
                else:
                    _r2_push_arg = (
                        f'Short-stack open-shove ({_cards} {_pos} {_stack:.0f}BB) '
                        f'— standard by stack depth, but push-chart membership is '
                        f'unresolved; verify against the nearest chart before '
                        f'treating it as automatic.')
                return {'verdict': 'III.5 Justified', 'outcome': 'standard_push',
                        'confidence': 'HIGH' if _in_push is True else 'MEDIUM',
                        'auto_rule': 'R2_open_shove_push',
                        'membership_resolved': _in_push is True,
                        'argument': _build_math_argument(_r2_push_arg, 'III.5')}

            # R3/R4: 3-bet jammer — eq splits flip vs cooler
            if _role == 'threebet_jam':
                if _eq_av >= _FLIP_LO:
                    # v8.12.8 QA-GPT P0.4: this phrase claimed "inside the
                    # jamming range" purely from equity while the
                    # membership line below said OUTSIDE (66313409,
                    # 66697168). One boolean (_in_rj) drives both.
                    if _in_rj is True:
                        # inside the rejam chart -> the chart IS the decision-time
                        # justification, so a near-flip get-in is standard.
                        return {'verdict': 'III.5 Justified', 'outcome': 'lost_flip',
                                'confidence': 'HIGH', 'auto_rule': 'R3_3betjam_flip',
                                'argument': _build_math_argument(
                                    f'3-bet jam as a near-flip ({_eq_av*100:.0f}% equity), '
                                    f'inside the jamming range — standard get-in.',
                                    'III.5')}
                    # v8.14.1 (GPT rev): an OUTSIDE-chart (or no-chart) rejam is NOT a
                    # "standard get-in" — near-flip ALL-IN (result) equity alone is not
                    # a decision-time justification, and labelling it "standard get-in"
                    # contradicts the OUTSIDE range-evidence block (73279700, 73720606).
                    # Downgrade to read-dependent and name the missing justification so
                    # the verdict never asserts a chart jam it cannot back.
                    _rj_oos = ('outside the standard jamming range' if _in_rj is False
                               else 'no rejam chart for this matchup')
                    return {'verdict': 'III.4 Read-dependent', 'outcome': 'lost_flip',
                            'confidence': 'MEDIUM',
                            'auto_rule': 'R3_3betjam_flip_unconfirmed',
                            'argument': _build_math_argument(
                                f'3-bet jam as a near-flip ({_eq_av*100:.0f}% equity), '
                                f'{_rj_oos} — equity-driven get-in; justify by '
                                f'fold-equity / price / opponent range, not a chart jam. '
                                f'Needs read or population confirmation.',
                                'III.4')}
                else:
                    # v8.5.8: only I.7 Cooler for genuine structural matchups
                    # (pair-over-pair). Non-pair jams that ran into the top of
                    # villain's range are III.5 Justified (correct play, variance).
                    _is_structural_cooler = False
                    _hero_pair = len(_cards) == 2 and _cards[0] == _cards[1]
                    if _hero_pair:
                        # Check if villain also has a higher pair (pair-over-pair)
                        for _mm in (h.get('matchups') or {}).values():
                            _vc = _mm.get('villain_hand_class', '') or ''
                            if len(_vc) >= 2 and _vc[0] == _vc[1]:
                                _vr = 'AKQJT98765432'.index(_vc[0]) if _vc[0] in 'AKQJT98765432' else 99
                                _hr = 'AKQJT98765432'.index(_cards[0]) if _cards[0] in 'AKQJT98765432' else 99
                                if _hr > _vr:
                                    _is_structural_cooler = True
                                    break
                    if _is_structural_cooler:
                        return {'verdict': 'I.7 Cooler', 'confidence': 'HIGH',
                                'auto_rule': 'R4_3betjam_cooler',
                                'argument': _build_math_argument(
                                    f'3-bet jam with {_cards} into {_vc} — pair-over-pair '
                                    f'({_eq_av*100:.0f}% equity). Structural cooler.',
                                    'I.7')}
                    else:
                        # v8.8.9 BUG-6: range membership gates the verdict label.
                        # Out-of-range jam → III.4, in-range (or unknown) → III.5.
                        _won_flag = net >= 0
                        _r4_result = 'won despite domination' if _won_flag else 'ran into top of calling range'
                        if _in_rj is not None and not _in_rj:
                            return {'verdict': 'III.4 Read-dependent', 'confidence': 'MEDIUM',
                                    'auto_rule': 'R4_3betjam_out_of_range',
                                    'argument': _build_math_argument(
                                        f'3-bet jam outside standard rejam range '
                                        f'({_eq_av*100:.0f}% equity), {_r4_result}. '
                                        f'Needs read/population confirmation.',
                                        'III.4')}
                        return {'verdict': 'III.5 Justified', 'confidence': 'HIGH',
                                'auto_rule': 'R4_3betjam_dominated',
                                'argument': _build_math_argument(
                                    f'3-bet jam {_r4_result} '
                                    f'({_eq_av*100:.0f}% equity). Standard get-in.',
                                    'III.5')}

            # v8.3.1: Apply PKO bounty credit to the call threshold.
            # bounty_discount_pp lowers the equity needed to call profitably.
            _bounty_pp = h.get('bounty_discount_pp', 0) or 0
            # v8.12.8 QA-GPT P0.2: the flat estimate ASSUMES Hero covers;
            # the pot-odds engine checks the real stacks. If it priced this
            # hand and applied NO discount, the TL;DR must not claim a
            # bounty-adjusted threshold next to "Bounty: no discount"
            # (66796475/65237018/65958832).
            _po_b9 = ctx.get('pot_odds') or {}
            if (_po_b9 and _po_b9.get('mode') != 'street_calls'
                    and _po_b9.get('required_eq_bounty_pct') is None):
                _bounty_pp = 0
            _adj_threshold = max(0.25, _CALL_PRICED_EQ - _bounty_pp / 100.0)
            _bounty_note = f' (bounty-adjusted threshold: {_adj_threshold*100:.0f}%)' if _bounty_pp > 0 else ''

            # R5: Caller of jam at near-flip equity (≥ adjusted threshold)
            if _role in ('caller', 'caller_vs_jam') and _eq_av >= _adj_threshold:
                return {'verdict': 'III.5 Justified', 'outcome': 'priced_call',
                        'confidence': 'HIGH', 'auto_rule': 'R5_call_jam_priced',
                        'argument': _build_math_argument(
                            f'Called the jam getting the right price '
                            f'({_eq_av*100:.0f}% equity{_bounty_note}) — standard, lost to variance.',
                            'III.5')}

            # R6: Caller of jam BELOW adjusted threshold
            # v8.9.8 P2-B: at micro-stacks, use actual pot odds from decision_math
            # instead of the static threshold. At <6BB the price often justifies
            # a call that the raw equity threshold would reject.
            if _role in ('caller', 'caller_vs_jam') and _eq_av < _adj_threshold:
                _dm_req = _st_data.get('required_equity') if _has_math else None
                _dm_call = _st_data.get('hero_call_amount_bb') if _has_math else None
                _eff = h.get('eff_stack_bb', h.get('stack_bb', 99)) or 99
                if (_dm_req is not None and _eff < 6
                        and _dm_req < 0.30 and _eq_av >= 0.15):
                    return {'verdict': 'III.5 Justified', 'outcome': 'priced_call',
                            'confidence': 'MEDIUM', 'auto_rule': 'R5_micro_potodds',
                            'needs_confirm': True,
                            'argument': _build_math_argument(
                                f'Called a micro-stack jam — pot odds required only '
                                f'{_dm_req*100:.0f}% equity, Hero had {_eq_av*100:.0f}%'
                                f'{_bounty_note}. Priced call at {_eff:.0f}BB eff.',
                                'III.5')}
                if _eq_av < 0.25:
                    if _dm_req is None and _eff < 6:
                        return {'verdict': 'III.4 Read-dependent', 'confidence': 'LOW',
                                'auto_rule': 'R6_call_jam_lowEq_nopotdata',
                                'needs_confirm': True,
                                'argument': _build_math_argument(
                                    f'Called a jam at {_eq_av*100:.0f}% equity (micro-stack '
                                    f'{_eff:.0f}BB but pot-odds data unavailable). '
                                    f'Routed to read-dependent — pot price may justify.',
                                    'III.4')}
                    return {'verdict': 'III.4 Read-dependent', 'confidence': 'MEDIUM',
                            'auto_rule': 'R6_call_jam_lowEq',
                            'needs_confirm': True,
                            'argument': _build_math_argument(
                                f'Called a jam well below threshold ({_eq_av*100:.0f}% equity vs '
                                f'{_adj_threshold*100:.0f}% needed{_bounty_note}). '
                                f'Likely dominated — verdict depends on read of villain\'s jam range.',
                                'III.4')}
                else:
                    return {'verdict': 'I.7 Cooler', 'confidence': 'MEDIUM',
                            'auto_rule': 'R6_call_jam_lowEq',
                            'needs_confirm': True,
                            'argument': _build_math_argument(
                                f'Called a jam below threshold ({_eq_av*100:.0f}% equity{_bounty_note}). '
                                f'Proposed cooler — confirm pot odds / bounty made the call correct.',
                                'I.7')}

        # R14: Fold to 4-bet at short depth
        if _role == 'folder' and h.get('hero_faced_raise') and _stack < 20:
            # Check if this looks like a fold to a 4-bet (Hero opened/3bet, then folded)
            if h.get('pfr') or h.get('hero_3bet'):
                if not pf_allin and not h.get('went_to_sd'):
                    return {'verdict': 'III.3 Cleared', 'confidence': 'HIGH',
                            'auto_rule': 'R14_fold_to_4bet',
                            'argument': f'**TL;DR:** Folded {_cards} to a 4-bet at '
                                        f'{_stack:.0f}BB — standard disciplined laydown.'}

        # ---- Legacy bucket-specific logic (kept for postflop/bestplay/iii4) ----

        # ---- Cooler bucket → I.7 Cooler ----
        if bucket == 'coolers':
            # v8.4.1: use RANGE equity for argument (not realized vs shown combo)
            _po = ctx.get('pot_odds', {}) or ctx.get('decision_math', {}).get(
                'streets', {}).get('preflop', {}) or {}
            _range_eq = _po.get('hero_eq_pct') or _po.get('hero_equity_pct')
            eq = eai.get('hero_equity') if eai else None
            # For flip/cooler classification, use realized equity
            if eq is not None and 0.40 <= eq <= 0.60:
                return {'verdict': 'III.5 Justified',
                        'outcome': 'lost_flip',
                        'confidence': 'HIGH',
                        'argument': f'**TL;DR:** Coin-flip at {eq*100:.0f}% equity. '
                                    f'{_cards} in the {_pos}, {_stack:.0f}BB deep. '
                                    f'Race — no decision error. Pure variance.'
                                    f'{_equity_line}{_push_range_note}',
                        'reason': f'Equity {eq*100:.0f}% at all-in = coin-flip'}
            # For cooler argument, narrate range equity (not realized vs result)
            _arg_eq = f'{_range_eq:.0f}% vs range' if _range_eq else (
                f'{eq*100:.0f}% realized' if eq is not None else 'equity unavailable')
            return {'verdict': 'I.7 Cooler',
                    'confidence': 'HIGH',
                    'argument': f'**TL;DR:** Structural cooler — unavoidable '
                                f'big-vs-big. {_cards} in the {_pos}, {_arg_eq}. '
                                f'No line adjustment avoids this loss.'
                                f'{_equity_line}{_push_range_note}',
                    'reason': 'Structural cooler — unavoidable big-vs-big'}

        # ---- Bust audit → classify by equity outcome ----
        if bucket == 'bust_audit':
            if voc == 'suckout':
                eq = eai.get('hero_equity', 0) if eai else 0
                _eq_pct = eq * 100 if eq <= 1.5 else eq
                return {'verdict': 'III.5 Justified',
                        'outcome': 'suckout',
                        'confidence': 'HIGH',
                        'argument': _build_math_argument(
                            f'Suckout — Hero was {_eq_pct:.0f}% favourite at all-in '
                            f'and lost. {_cards} in the {_pos}. Correct get-in, '
                            f'wrong side of variance.', 'III.5'),
                        'reason': 'Hero was equity favourite and lost'}
            if voc == 'lost_flip':
                eq = eai.get('hero_equity', 0) if eai else 0
                # Use multiway field_equity when available (more accurate)
                _mwd = ctx.get('multiway_decomposition') or {}
                if _mwd.get('field_equity') is not None:
                    eq = _mwd['field_equity'] / 100.0
                # Don't label as "flip" if equity < 35% — that's a dog
                if eq and eq < 0.35:
                    return {'verdict': 'III.4 Read-dependent',
                            'outcome': 'multiway_dog',
                            'confidence': 'MEDIUM',
                            'argument': f'**TL;DR:** Multiway all-in at {eq*100:.0f}% '
                                        f'equity — below flip threshold. {_cards} in the '
                                        f'{_pos}. Defensible only on bounty/price.'
                                        f'{_equity_line}{_push_range_note}',
                            'reason': f'Multiway dog at {eq*100:.0f}% — not a standard race'}
                _eq_pct2 = eq * 100 if eq <= 1.5 else eq
                return {'verdict': 'III.5 Justified',
                        'outcome': 'lost_flip',
                        'confidence': 'HIGH',
                        'argument': _build_math_argument(
                            f'Lost flip at {_eq_pct2:.0f}% equity. {_cards} in the '
                            f'{_pos}, {_stack:.0f}BB. Standard race — no decision '
                            f'error.', 'III.5'),
                        'reason': 'Coin-flip equity at all-in'}
            if voc == 'top_of_range':
                # CP22: don't auto-tag as cooler if Hero didn't commit
                # most of their stack. A 4BP x/f that lost 20BB of 125BB
                # is a read-dependent fold, not a structural cooler.
                _committed = h.get('hero_committed_bb') or abs(net)
                _stack_frac = _committed / max(_stack, 1) if _stack else 1
                if _stack_frac < 0.5 and not pf_allin:
                    return {'verdict': 'III.4 Read-dependent',
                            'confidence': 'MEDIUM',
                            'argument': f'**TL;DR:** Faced villain value line, '
                                        f'folded without committing stack. '
                                        f'{_cards} in the {_pos}, {_stack:.0f}BB. '
                                        f'Review the flat/call decision, not the fold.'
                                        f'{_equity_line}',
                            'reason': 'Partial-stack loss — read-dependent, not cooler'}
                return {'verdict': 'I.7 Cooler',
                        'confidence': 'MEDIUM',
                        'argument': f'**TL;DR:** Ran into top of villain range. '
                                    f'{_cards} in the {_pos}, {_stack:.0f}BB.'
                                    f'{_equity_line}{_push_range_note}',
                        'reason': 'Hero ran into top of villain range'}
            if voc == 'semi_bluff_cooler':
                return {'verdict': 'III.5 Justified',
                        'outcome': 'variance',
                        'confidence': 'MEDIUM',
                        'argument': f'**TL;DR:** Variance — semi-bluff cooler '
                                    f'structure. {_cards} in the {_pos}.',
                        'reason': 'Variance — semi-bluff/cooler structure'}
            return None

        # ---- Punts → III.1 Punt ----
        if bucket == 'punts':
            _punt_arg = _push_range_note or ''  # cite push range if applicable
            return {'verdict': 'III.1 Punt',
                    'confidence': 'MEDIUM',
                    'argument': _punt_arg,
                    'reason': f'Detector-flagged punt: {_cards} {_pos} '
                              f'{_stack:.0f}BB — {_act[:50]}'}

        # ---- Mistakes → III.2 Mistake ----
        if bucket == 'mistakes':
            _mtype = ctx.get('mistake_type', '') or ''
            _conf = ctx.get('confidence', ctx.get('mistake_severity', ''))
            # D1: MARGINAL missed-steals are mostly correct folds — don't
            # pre-label as III.2. Route to screening instead.
            if 'MARGINAL' in str(_conf).upper() and 'Missed Steal' in _mtype:
                return {'verdict': '',  # analyst decides
                        'confidence': 'LOW',
                        'argument': '',
                        'reason': f'Marginal missed steal: {_cards} {_pos} '
                                  f'{_stack:.0f}BB — likely correct fold per '
                                  f'SB/fold-band rules. Confirm before promoting.'}
            # CLEAR mistakes get real pre-fill
            if 'CLEAR' in str(_conf).upper():
                return {'verdict': 'III.2 Mistake',
                        'confidence': 'HIGH',
                        'argument': f'**TL;DR:** {_mtype}. {_cards} in the {_pos}, '
                                    f'{_stack:.0f}BB. {_act[:60]}',
                        'reason': f'CLEAR {_mtype}: {_cards} {_pos} {_stack:.0f}BB'}
            return {'verdict': 'III.2 Mistake',
                    'confidence': 'MEDIUM',
                    'argument': '',
                    'reason': f'{_mtype or "Detector-flagged"}: {_cards} {_pos} '
                              f'{_stack:.0f}BB — {_act[:50]}'}

        # ---- III.4 screening → pre-fill with context ----
        if bucket == 'iii4_screening':
            _eq = eai.get('hero_equity') if eai else None
            _eq_str = f'{_eq*100:.0f}% equity at all-in' if _eq else ''
            return {'verdict': '',  # analyst decides
                    'confidence': 'MEDIUM',
                    'argument': f'**TL;DR:** {_cards} in the {_pos}, {_stack:.0f}BB. '
                                f'{(_eq_str + ". ") if _eq_str else ""}{_dp_str or _act[:60]}',
                    'reason': f'III.4 screening: {_cards} {_pos} {_stack:.0f}BB — '
                              f'needs analyst decision on verdict category'}

        # ---- Read-dependent → pre-fill with solver context ----
        if bucket == 'read_dependent_screening':
            return {'verdict': 'III.4 Read-dependent',
                    'confidence': 'MEDIUM',
                    'argument': f'**TL;DR:** {_cards} in the {_pos}, {_stack:.0f}BB. '
                                f'{_dp_str or _act[:60]}. '
                                f'Result-independent — grade on population EV.',
                    'reason': f'Read-dependent: {_cards} {_pos} — '
                              f'verdict flips between GTO and population range'}

        # ---- Bestplay → pre-fill structural screen ----
        if bucket == 'bestplay_screening':
            _bp_reasons = ctx.get('bestplay_screen', {}).get('reasons', [])
            return {'verdict': '',  # analyst curates
                    'confidence': 'LOW',
                    'argument': '',
                    'reason': f'Pick candidate: {"; ".join(_bp_reasons[:3])}'}

        # ---- All-in review → classify by equity + math ----
        if bucket == 'all_in_review':
            eq = eai.get('hero_equity') if eai else None
            _eq_pct = (eq * 100 if eq is not None and eq <= 1.5 else eq) if eq is not None else None
            _vd = _dm.get('verdict_direction', 'unknown') if _dm else 'unknown'
            if eq is not None and _eq_pct is not None:
                if _eq_pct >= 55:
                    return {'verdict': 'III.5 Justified',
                            'outcome': 'ahead',
                            'confidence': 'HIGH',
                            'argument': _build_math_argument(
                                f'All-in as {_eq_pct:.0f}% favourite. {_cards} in '
                                f'the {_pos}, {_stack:.0f}BB. Standard get-in.',
                                'III.5'),
                            'reason': f'Ahead at {_eq_pct:.0f}%'}
                elif _eq_pct >= 42:
                    return {'verdict': 'III.5 Justified',
                            'outcome': 'flip',
                            'confidence': 'HIGH',
                            'argument': _build_math_argument(
                                f'Flip at {_eq_pct:.0f}%. {_cards} in the {_pos}, '
                                f'{_stack:.0f}BB. Race — no decision error.',
                                'III.5'),
                            'reason': f'Flip at {_eq_pct:.0f}%'}
                else:
                    # Behind — check if bounty-justified or avoidable
                    _fmt = (h.get('format') or '').upper()
                    _is_bounty = _fmt in ('BOUNTY', 'PKO', 'MYSTERY_BOUNTY')
                    if _is_bounty and _eq_pct >= 34:
                        return {'verdict': 'III.5 Justified',
                                'outcome': 'bounty_call',
                                'confidence': 'MEDIUM',
                                'argument': _build_math_argument(
                                    f'Behind at {_eq_pct:.0f}% but bounty format — '
                                    f'~8pp discount makes this breakeven/+EV. '
                                    f'{_cards} in the {_pos}, {_stack:.0f}BB.',
                                    'III.5'),
                                'reason': f'Bounty-justified at {_eq_pct:.0f}%'}
                    elif _stack and _stack <= 12:
                        return {'verdict': 'III.5 Justified',
                                'outcome': 'forced_jam',
                                'confidence': 'HIGH',
                                'argument': _build_math_argument(
                                    f'Forced jam at {_stack:.0f}BB with {_cards}. '
                                    f'Below push/fold threshold — no fold EV. '
                                    f'{_eq_pct:.0f}% at all-in.',
                                    'III.5'),
                                'reason': f'Short-stack forced jam at {_stack:.0f}BB'}
                    else:
                        return {'verdict': '',  # analyst decides
                                'confidence': 'MEDIUM',
                                'argument': _build_math_argument(
                                    f'Behind at {_eq_pct:.0f}% with {_cards} in '
                                    f'the {_pos}, {_stack:.0f}BB. Review whether '
                                    f'the call/jam was +EV given the price.',
                                    ''),
                                'reason': f'Behind at {_eq_pct:.0f}% — review'}
            return None

        return None

    # SPEC #3: compute per-street decision math on every candidate
    _n_math = 0
    for _bk_math in ('bust_audit', 'coolers', 'mistakes', 'punts',
                      'iii4_screening', 'read_dependent_screening',
                      'bestplay_screening', 'all_in_review'):
        for _ctx_math in candidates.get(_bk_math, []) or []:
            if not isinstance(_ctx_math, dict):
                continue
            _hid_m = _ctx_math.get('id', '')
            _h_m = hands_by_id.get(_hid_m, {})
            if _h_m:
                _dm = _compute_decision_math(_h_m, _ctx_math)
                _ctx_math['decision_math'] = _dm
                _n_math += 1
    print(f"  decision math: {_n_math} candidates have per-street pot-odds/equity")

    _t0_verdict = _time.perf_counter()
    _n_prefilled = 0
    # v8.12.4 (QA item 10): a hand sitting in the SUCKOUT ledger (equity
    # favourite, lost) is pure variance by the pipeline's own accounting —
    # a worksheet prefill sourced from the `mistakes` candidate bucket must
    # not carry HIGH confidence for the same hand. Cap to MEDIUM + caution.
    _suckout_ids_pf = {e.get('id') for e in
                       (stats.get('suckouts', {}) or {}).get('against_hero', [])
                       if isinstance(e, dict)}
    for _bk_pf in ('bust_audit', 'coolers', 'mistakes', 'punts',
                    'iii4_screening', 'read_dependent_screening',
                    'bestplay_screening', 'all_in_review'):
        for _ctx_pf in candidates.get(_bk_pf, []) or []:
            if not isinstance(_ctx_pf, dict):
                continue
            pf = _prefill_verdict(_ctx_pf, _bk_pf)
            if pf:
                if (_ctx_pf.get('id') in _suckout_ids_pf
                        and _bk_pf in ('mistakes', 'punts')
                        and pf.get('confidence') == 'HIGH'):
                    pf['confidence'] = 'MEDIUM'
                    pf['argument'] = ((pf.get('argument') or '')
                                      + ' [CAUTION: this hand is in the '
                                        'suckout ledger — equity favourite '
                                        'lost. Verify agency before any '
                                        'mistake verdict.]').strip()
                _ctx_pf['suggested_verdict'] = pf
                _n_prefilled += 1
    _t_verdict = _time.perf_counter() - _t0_verdict
    print(f"  pre-filled verdicts: {_n_prefilled} candidates have suggested verdicts ({_t_verdict:.1f}s)")

    # v8.8.9 BUG-3: Pipe HIGH-confidence auto-verdicts to the renderer so
    # the hand modal always shows a verdict block (analyst → auto → pending).
    _auto_verdicts = {}
    for _bk_av in candidates:
        for _ctx_av in candidates.get(_bk_av, []) or []:
            if not isinstance(_ctx_av, dict):
                continue
            _sv_av = _ctx_av.get('suggested_verdict')
            if isinstance(_sv_av, dict) and _sv_av.get('confidence') == 'HIGH':
                _hid_av = _ctx_av.get('id', '')
                if _hid_av and _hid_av not in _auto_verdicts:
                    _auto_verdicts[_hid_av] = {
                        'verdict': _sv_av.get('verdict', ''),
                        'auto_rule': _sv_av.get('auto_rule', ''),
                        'argument': _sv_av.get('argument', ''),
                    }
    report_data['auto_verdicts'] = _auto_verdicts
    if _auto_verdicts:
        print(f"  auto-verdicts piped to renderer: {len(_auto_verdicts)}")

    # ---- BATCH 3 (#2): ROOT MISTAKE ATTRIBUTION ----
    # For each candidate hand with decision_points, identify whether the root
    # mistake was on an earlier street than the key decision.
    # Simple heuristic: if Hero cold-called/flatted preflop (passive entry)
    # and later lost, the preflop entry is the root mistake.
    _n_root = 0
    for _bk_rm in ('bust_audit', 'mistakes', 'punts', 'iii4_screening'):
        for _ctx_rm in candidates.get(_bk_rm, []) or []:
            if not isinstance(_ctx_rm, dict):
                continue
            _hid_rm = _ctx_rm.get('id', '')
            _h_rm = hands_by_id.get(_hid_rm, {})
            if not _h_rm:
                continue
            dps = _h_rm.get('decision_points') or []
            if len(dps) < 2:
                continue
            # Find preflop DP
            _pf_dp = next((d for d in dps if d.get('street') == 'preflop'), None)
            # Find key decision
            _key_dp = next((d for d in dps if d.get('is_key_decision')), None)
            if not _pf_dp or not _key_dp:
                continue
            if _key_dp['street'] == 'preflop':
                continue  # key decision IS preflop, no root attribution needed
            # If preflop action was a passive entry (cold_call, defend via flat)
            # and the hand lost, mark preflop as root mistake
            _pf_class = _pf_dp.get('hero_action_class', '')
            if _pf_class in ('cold_call', 'defend', 'call_bet') and (_h_rm.get('net_bb', 0) < -5):
                _pf_dp['is_root_mistake'] = True
                _pf_dp['downstream_of'] = None
                _key_dp['downstream_of'] = _pf_dp['id']
                _key_dp['is_root_mistake'] = False
                _ctx_rm['root_mistake_street'] = 'preflop'
                _ctx_rm['root_mistake_action'] = _pf_class
                _n_root += 1
    if _n_root:
        print(f"  root mistakes: {_n_root} hands have preflop root attribution")

    # ---- WIRING: POPULATION EXPLOITS on candidate decision_points ----
    _n_exploits = 0
    try:
        from gem_population_exploits import classify_spot, get_exploit_for_spot
        for _bk_ex in ('bust_audit', 'mistakes', 'punts', 'iii4_screening',
                        'read_dependent_screening'):
            for _ctx_ex in candidates.get(_bk_ex, []) or []:
                if not isinstance(_ctx_ex, dict):
                    continue
                _hid_ex = _ctx_ex.get('id', '')
                _h_ex = hands_by_id.get(_hid_ex, {})
                for _dp_ex in (_h_ex.get('decision_points') or []):
                    _spot = classify_spot(_h_ex, _dp_ex)
                    if _spot:
                        _arch = _dp_ex.get('facing_villain_snapshot', {})
                        _v_arch = (_h_ex.get('villains', {}).get(
                            _dp_ex.get('facing_villain_name', ''), {}
                        ).get('archetype'))
                        _exploit = get_exploit_for_spot(_spot, _v_arch)
                        if _exploit:
                            _dp_ex['population_note'] = _exploit.get('exploit', '')
                            _dp_ex['villain_specific_note'] = _exploit.get('villain_note')
                            _n_exploits += 1
        if _n_exploits:
            print(f"  population exploits: {_n_exploits} decision points annotated")
    except Exception as _ex_err:
        print(f"  population exploits: skipped ({_ex_err})")

    # ---- WIRING: AUTO NARRATIVE ----
    try:
        from gem_auto_narrative import generate_session_narrative
        _narrative = generate_session_narrative(stats, report_data, hands)
        # Store as fallback synthesis — analyst can override
        _ac = report_data.get('analyst_commentary', {})
        if isinstance(_ac, dict) and '__synthesis__' not in _ac:
            _ac.setdefault('__auto_synthesis__', _narrative)
            report_data['analyst_commentary'] = _ac
            print(f"  auto narrative: \"{_narrative.get('headline', '?')[:60]}...\"")
    except Exception as _an_err:
        print(f"  auto narrative: skipped ({_an_err})")

    def _build_key_decision_prefill(ctx, h):
        """Pre-fill key_decision with street + pot-odds from decision_math."""
        dm = ctx.get('decision_math', {})
        if not dm:
            return ''
        key_st = dm.get('key_decision_street', '')
        st_data = (dm.get('streets', {}) or {}).get(key_st, {})
        if not st_data:
            return ''
        req = st_data.get('required_equity')
        call = st_data.get('hero_call_amount_bb')
        pot = st_data.get('pot_facing_hero_bb')
        if req and call and pot:
            return f'{key_st}: call {call:.1f}BB into {pot:.1f}BB, need {req*100:.0f}%'
        return ''

    # ---- EFFICIENCY #3: COVERAGE DRY-RUN ----
    # Summary at the top of candidates file: what needs analyst, what's auto-resolvable
    _n_needs_analyst = 0
    _n_auto = 0
    for _bk_dr in ('bust_audit', 'coolers', 'mistakes', 'punts',
                    'iii4_screening', 'read_dependent_screening',
                    'bestplay_screening'):
        for _ctx_dr in candidates.get(_bk_dr, []) or []:
            if isinstance(_ctx_dr, dict) and _ctx_dr.get('suggested_verdict'):
                conf = _ctx_dr['suggested_verdict'].get('confidence', '')
                if conf == 'HIGH':
                    _n_auto += 1
                else:
                    _n_needs_analyst += 1
            else:
                _n_needs_analyst += 1
    candidates['coverage_summary'] = {
        'total_candidates': sum(len(candidates.get(b, [])) for b in
            ('bust_audit', 'coolers', 'mistakes', 'punts',
             'iii4_screening', 'read_dependent_screening', 'bestplay_screening')),
        'auto_resolvable': _n_auto,
        'needs_analyst': _n_needs_analyst,
        'blindspot_sample': len(candidates.get('blindspot_sample', [])),
        'note': f'{_n_auto} hands have HIGH-confidence pre-filled verdicts '
                f'(confirm with one word). {_n_needs_analyst} need full analyst review.',
    }
    print(f"  coverage dry-run: {_n_auto} auto-resolvable, "
          f"{_n_needs_analyst} need analyst, "
          f"{len(candidates.get('blindspot_sample', []))} blindspot")

    # RC3 P0-2: populate the loss-screen buckets from the EARLY-computed _loss_screens BEFORE the
    # analyst_candidates file is written (these were previously populated ~230 lines too late, so the
    # persisted contract shipped them empty). Each screened hand must be cleared/classified.
    for _blid in _loss_screens['biggest_loss_screen']:
        _bctx = _hand_ctx(_blid)
        _bctx['screen_reason'] = 'Per-tournament biggest loss; must clear or classify.'
        candidates['biggest_loss_screen'].append(_bctx)
    for _plid in _loss_screens['postflop_loss_screen']:
        _pctx = _hand_ctx(_plid)
        _net_pl = (hands_by_id.get(_plid, {}) or {}).get('net_bb', 0) or 0
        _pctx['screen_reason'] = (
            f'Postflop loss {_net_pl:.0f}BB (<= {POSTFLOP_LOSS_SCREEN_BB:.0f}BB); '
            'must clear or classify.')
        candidates['postflop_loss_screen'].append(_pctx)
    report_data['loss_screen_counts'] = {
        'biggest_loss_screen': len(candidates['biggest_loss_screen']),
        'postflop_loss_screen': len(candidates['postflop_loss_screen']),
    }
    # v8.20 W1A: stamp the ONE canonical material-loss population (records keyed on the screened ids,
    # enriched with nominating detector families). analyst_status/final_classification start UNGRADED and
    # are filled by compute_report_completeness when analyst_commentary is live (full + --quick paths),
    # so every material loss ends in exactly one visible state and none can silently disappear.
    import gem_material_loss as _mloss
    _blind_ids = {c.get('id') for c in (candidates.get('blindspot_sample', []) or [])
                  if isinstance(c, dict) and c.get('id')}
    _mpop = _mloss.build_material_loss_population(
        _loss_screens, hands, candidates=candidates,
        analyst_commentary=report_data.get('analyst_commentary'),
        blindspot_ids=_blind_ids, stack_trajectories=stats.get('stack_trajectories'))
    report_data['material_loss_population'] = _mpop
    report_data['material_loss_summary'] = _mloss.material_loss_summary(_mpop)

    with open(cand_path, 'w', encoding='utf-8') as f:
        json.dump(candidates, f, indent=2, default=str, ensure_ascii=False)

    # ---- W1: MERGED ANALYST WORKSHEET ----
    # One file replaces both the old template AND candidates cross-reference.
    # Each entry has: full context (all 55 fields from _hand_ctx) +
    # writable verdict fields + pre-fill + pot_odds + draw_profiles.
    # The analyst works in THIS file — no cross-referencing needed.
    _date_range = stats['volume']['date_range']
    _worksheet_path = f'/home/claude/analyst_worksheet_{_pname_file}_{_date_range}.json'
    _valid_verdicts = ['III.1 Punt', 'III.2 Mistake', 'III.3 Cleared',
                       'III.4 Read-dependent', 'III.5 Justified', 'I.7 Cooler']
    _worksheet = {}
    for _bk_t in ('bust_audit', 'coolers', 'mistakes', 'punts',
                   'iii4_screening', 'read_dependent_screening',
                   'bestplay_screening', 'big_river_calldowns'):
        for _ctx_t in candidates.get(_bk_t, []) or []:
            hid = _ctx_t.get('id', '')
            if not hid:
                continue
            sv = _ctx_t.get('suggested_verdict', {})
            # v8.3.0: Skip noise-suppressed hands (R0) — don't put them in the worksheet
            if sv.get('verdict') == 'SUPPRESS':
                continue
            po = _ctx_t.get('pot_odds', {})
            h = hands_by_id.get(hid, {})
            # Full context — everything the analyst needs, no cross-reference
            _worksheet[hid] = {
                # ---- WRITABLE FIELDS (analyst fills/confirms) ----
                'verdict': sv.get('verdict', ''),
                'outcome': sv.get('outcome', ''),
                'argument': sv.get('argument', ''),
                'spot': f"{h.get('position','?')} {h.get('stack_bb',0):.0f}BB, "
                        f"{h.get('tournament_phase','').replace('_',' ')}, "
                        f"{_ctx_t.get('action_summary','')}",
                # v8.4.0: pre-fill key_decision from decision_math pot-odds
                'key_decision': _build_key_decision_prefill(_ctx_t, h),
                'street': '',
                'one_two_back': '',
                'matchup_math': '',
                # ---- PRE-FILL METADATA ----
                '_prefill_confidence': sv.get('confidence', ''),
                '_prefill_reason': sv.get('reason', ''),
                '_auto_rule': sv.get('auto_rule', ''),
                '_needs_confirm': sv.get('needs_confirm', False),
                '_source_bucket': _bk_t,
                '_valid_verdicts': _valid_verdicts,
                # ---- FULL CONTEXT (from _hand_ctx, inline) ----
                '_cards': _ctx_t.get('cards', ''),
                '_position': _ctx_t.get('position', ''),
                '_stack_bb': _ctx_t.get('stack_bb', 0),
                '_eff_stack_bb': _ctx_t.get('effective_stack_bb'),
                '_eff_stack_at_decision': _ctx_t.get('eff_stack_at_decision_bb'),
                '_spr': _ctx_t.get('spr'),
                '_net_bb': _ctx_t.get('net_bb', 0),
                '_won': _ctx_t.get('won'),
                '_board': ' '.join(h.get('board', []) or []),
                '_board_texture': _ctx_t.get('board_texture', ''),
                '_board_archetype': _ctx_t.get('board_archetype', ''),
                '_pot_type': _ctx_t.get('pot_type', ''),
                '_format': _ctx_t.get('format', ''),
                '_tournament_phase': _ctx_t.get('tournament_phase', ''),
                '_hand_strength': _ctx_t.get('hand_strength', ''),
                '_players_at_flop': _ctx_t.get('players_at_flop', 0),
                '_hero_realized_eq_at_allin': _ctx_t.get('hero_realized_eq_at_allin'),
                '_draw_profiles': _ctx_t.get('draw_profiles', {}),
                '_board_state': _ctx_t.get('board_state', {}),
                '_action_summary': _ctx_t.get('action_summary', ''),
                '_action_sequence': _ctx_t.get('action_sequence', ''),
                '_line_actions': _ctx_t.get('line_actions', ''),
                '_pf_sequence': _ctx_t.get('pf_sequence', ''),
                '_hero_street_actions': _ctx_t.get('hero_street_actions', {}),
                '_vpip': _ctx_t.get('vpip', False),
                '_pfr': _ctx_t.get('pfr', False),
                '_hero_3bet': _ctx_t.get('hero_3bet', False),
                '_opener_position': _ctx_t.get('opener_position', ''),
                '_hero_cbet_flop': _ctx_t.get('hero_cbet_flop', False),
                '_double_barreled': _ctx_t.get('double_barreled', False),
                # ---- VILLAIN ARCHETYPE ----
                # ---- BOUNTY ESTIMATION ----
                '_bounty_type': _ctx_t.get('bounty_type', 'none'),
                '_bounty_discount_pp': _ctx_t.get('bounty_discount_pp', 0),
                '_bounty_value_bb': _ctx_t.get('bounty_value_bb', 0),
                '_bounty_label': _ctx_t.get('bounty_label', ''),
                # ---- VILLAIN ARCHETYPE + SHOWN CARDS ----
                '_villain_archetype': _ctx_t.get('villain_archetype', ''),
                '_villain_archetype_label': _ctx_t.get('villain_archetype_label', ''),
                '_villain_archetype_reason': _ctx_t.get('villain_archetype_reason', ''),
                '_villain_exploit_note': _ctx_t.get('villain_exploit_note', ''),
                # v8.4.0: fall back to per-seat shown_cards when primary_villain is empty
                '_villain_shown_cards': ((h.get('primary_villain', {}) or {}).get('shown_cards', [])
                    or next((v.get('shown_cards', []) for v in (h.get('villains', {}) or {}).values()
                             if v.get('shown_cards')), [])),
                # ---- POT ODDS (§3b math) ----
                # v8.12.8: mode 'street_calls' = non-all-in calldown block
                # (handover Issue 1) — per_street carries one display line
                # per call incl. the OVERBET flag; the analyst must use
                # these numbers, never eyeball the pot fraction.
                '_pot_odds': {
                    'call_bb': po.get('call_bb'),
                    'pot_bb': po.get('pot_bb'),
                    'required_eq_pct': po.get('required_eq_pct'),
                    'hero_eq_pct': po.get('hero_equity_pct'),
                    'verdict_hint': po.get('verdict_hint'),
                    'bounty_req_eq': po.get('required_eq_bounty_pct'),
                    'mode': po.get('mode', 'allin'),
                    'is_overbet': po.get('is_overbet'),
                    'per_street': po.get('per_street_summary'),
                } if po else None,
            }
    # Add blindspot sample entries
    for _bs_h in candidates.get('blindspot_sample', []) or []:
        _bs_id = _bs_h.get('id', '')
        if _bs_id and _bs_id not in _worksheet:
            _worksheet[_bs_id] = {
                'verdict': '', 'argument': '',
                'spot': f"Blindspot — {_bs_h.get('pos','?')} "
                        f"{_bs_h.get('stack_bb',0):.0f}BB",
                '_source_bucket': 'blindspot_sample',
                '_valid_verdicts': _valid_verdicts + ['No issue found'],
                '_cards': ' '.join(_bs_h.get('cards', []) or []),
                '_net_bb': _bs_h.get('net_bb', 0),
            }
    # v8.4.1: Add priority sections + summary so analyst knows the real surface
    _SECTION_PRIORITY = {
        'punts': (1, 'SIGNAL — Punts'),
        'mistakes': (2, 'SIGNAL — Mistakes'),
        'coolers': (3, 'SIGNAL — Coolers'),
        'bust_audit': (4, 'DECISION — Bust/Exit Hands'),
        'iii4_screening': (5, 'DECISION — Read-Dependent Screening'),
        'read_dependent_screening': (6, 'DECISION — Read-Dependent'),
        'blindspot_sample': (7, 'AUDIT — Blind-Spot Sample'),
        'bestplay_screening': (8, 'SCREENING — Confirm & Close'),
    }
    _section_counts = {}
    _signal_ids = []
    _decision_ids = []
    for hid, entry in _worksheet.items():
        if hid.startswith('__'):
            continue
        bk = entry.get('_source_bucket', 'bestplay_screening')
        pri, label = _SECTION_PRIORITY.get(bk, (9, 'OTHER'))
        entry['_priority_section'] = label
        entry['_priority_rank'] = pri
        _section_counts[label] = _section_counts.get(label, 0) + 1
        if pri <= 3:
            _signal_ids.append(hid)
        elif pri <= 6:
            _decision_ids.append(hid)
    # Add a summary header for the analyst
    _worksheet['__worksheet_summary__'] = {
        'total_entries': len([h for h in _worksheet if not h.startswith('__')]),
        'signal_hands': len(_signal_ids),
        'decision_hands': len(_decision_ids),
        'screening_hands': _section_counts.get('SCREENING — Confirm & Close', 0),
        'sections': dict(sorted(_section_counts.items(), key=lambda x: x[0])),
        'signal_hand_ids': _signal_ids,
        'decision_hand_ids': _decision_ids,
        'note': 'Start with signal hands, then decision hands. Screening is batch-confirm.',
        'pipeline_timing': {
            'parse_s': round(_t_parse, 1),
            'analyze_s': round(_t_analyze, 1),
            'profiler_s': round(_t_profiler, 1) if _t_profiler is not None else None,
            'verdicts_s': round(_t_verdict, 1) if _t_verdict is not None else None,
            'render_s': round(_t_render, 1) if _t_render is not None else None,
            'total_s': round(_time.perf_counter() - _t_pipeline_start, 1),
        },
        'analyst_timing': {
            'started_at': None,
            'signal_done_at': None,
            'decision_done_at': None,
            'screening_done_at': None,
            'synthesis_done_at': None,
            'finished_at': None,
            'note': 'Fill timestamps as you work. Pipeline reads these for efficiency tracking.',
        },
    }
    try:
        with open(_worksheet_path, 'w', encoding='utf-8') as _wf:
            json.dump(_worksheet, _wf, indent=2, default=str, ensure_ascii=False)
        print(f"  analyst worksheet: {_worksheet_path} "
              f"({len(_worksheet)} entries, {sum(1 for v in _worksheet.values() if isinstance(v, dict) and v.get('verdict'))} verdicts pre-filled, {_n_auto} auto-resolvable)")
        print(f"  Real surface: {len(_signal_ids)} signal + {len(_decision_ids)} decision "
              f"= {len(_signal_ids) + len(_decision_ids)} hands to review")
    except Exception as _we:
        print(f"  analyst worksheet generation failed: {_we}")
    # B157: suppress contradictory aggression flags on cooler/justified hands
    _cooler_justified_ids = set()
    for _wid, _wentry in _worksheet.items():
        _wv = (_wentry.get('verdict') or '')
        if _wv in ('I.7 Cooler', 'III.5 Justified'):
            _cooler_justified_ids.add(_wid)
    if _cooler_justified_ids:
        _agg_data = report_data.get('aggression_analysis', {})
        for _agg_bk in ('too_aggressive', 'ambiguous_aggressive'):
            if _agg_bk in _agg_data:
                _agg_data[_agg_bk] = [c for c in _agg_data[_agg_bk]
                                       if c.get('hand_id', '') not in _cooler_justified_ids]

    # Also write the old template for backward compat (renderer reads it)
    _template_path = f'/home/claude/session_analysis_{_pname_file}_{_date_range}_TEMPLATE.json'
    try:
        # Extract just the writable fields for backward compat
        _template = {hid: {k: v for k, v in entry.items() if not k.startswith('_')}
                     for hid, entry in _worksheet.items()}
        # v8.3.1: Add __synthesis__ stub so the analyst has the shape ready
        _template['__synthesis__'] = {
            'leaks': {},
            'mistakes_review': {},
            'session_narrative': '',
            'key_takeaway': '',
        }
        with open(_template_path, 'w', encoding='utf-8') as _tf:
            json.dump(_template, _tf, indent=2, default=str, ensure_ascii=False)
    except Exception:
        pass

    _n_bs = len(candidates.get('blindspot_sample', []))
    print(f"\nAnalyst candidates: {cand_path} "
          f"({len(candidates['bust_audit'])} bust + "
          f"{len(candidates['coolers'])} cooler + "
          f"{len(candidates['mistakes'])} mistake + "
          f"{len(candidates['punts'])} punt + "
          f"{len(candidates['iii4_screening'])} III.4 screening + "
          f"{len(candidates['read_dependent_screening'])} read-dep screening + "
          f"{len(candidates['bestplay_screening'])} bestplay screening + "
          f"{_n_bs} blindspot sample)")

    # ── v8.13.1 P1: coverage screens (biggest-loss + postflop-loss). These are
    #    COVERAGE rules, not mistake detectors — each screened hand must be
    #    cleared or classified by the analyst, and gates ANALYST_COMPLETE.
    # RC3 P0-2: the loss-screen population MOVED to before the analyst_candidates write above
    # (it previously ran here, ~250 lines after the file was already serialized, so the persisted
    # buckets shipped empty). _loss_screens is computed once near the top of build_and_write.

    # v7.60: surface the read-dependent screener output to the renderer so
    # the flagged calls are visible in III.4 this session (awaiting analyst
    # verdict), not only in the candidate file.
    report_data['read_dependent_screen'] = candidates.get(
        'read_dependent_screening', [])

    # B165 (Ron 2026-05-24): surface the bestplay (Pokerbot's Picks) screening
    # candidates so III.8 can list them and XIV.B can render the full grid —
    # lets Ron see what's been structurally screened and add archetype verdicts.
    report_data['bestplay_screen'] = candidates.get('bestplay_screening', [])

    return candidates
