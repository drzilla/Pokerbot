#!/usr/bin/env python3
"""
GEM Parser v72.0 — Pure hand history parsing.
Reads GGPoker hand histories, returns structured hand dicts.
No analysis, no metrics, no ranges. Testable in isolation.

Usage: Import from gem_analyzer.py (not run directly).
"""

import re, os, sys
from collections import defaultdict
from pathlib import Path
from itertools import combinations

# v7.31: GTO texture archetype classifier (Dave session 2026-05-04).
# Lives alongside the existing classify_board(); both are computed per hand.
try:
    from gem_textures import classify_archetype as _classify_archetype
    _HAS_TEXTURES = True
except ImportError:
    _HAS_TEXTURES = False
    def _classify_archetype(_): return 'unknown'

RANKS = '23456789TJQKA'
RANK_VAL = {r: i for i, r in enumerate(RANKS)}  # 2=0 .. A=12
RANK_NUM = {r: 14-i for i, r in enumerate('AKQJT98765432')}  # A=14 .. 2=2
RANKS_ORDER = 'AKQJT98765432'

def normalize_hand(cards):
    if len(cards) < 2: return ''
    r1, s1 = cards[0][0], cards[0][1]
    r2, s2 = cards[1][0], cards[1][1]
    i1 = RANKS_ORDER.index(r1) if r1 in RANKS_ORDER else 12
    i2 = RANKS_ORDER.index(r2) if r2 in RANKS_ORDER else 12
    if i1 > i2: r1, r2, s1, s2 = r2, r1, s2, s1
    return r1+r2 if r1==r2 else r1+r2+('s' if s1==s2 else 'o')

def pct(n, d): return round(n/d*100, 1) if d > 0 else 0.0

# ============================================================
# HAND EVALUATION
# ============================================================

def evaluate_best_hand(hero_cards, board):
    """Best 5-card hand from hero(2) + board(3-5). Returns (rank, name, kickers)."""
    all_c = hero_cards + board
    if len(all_c) < 5: return (0, 'high_card', [])
    best = (-1, 'unknown', [])
    for combo in combinations(all_c, 5):
        s = _score5(combo)
        if s[0] > best[0] or (s[0] == best[0] and s[2] > best[2]): best = s
    return best

def _score5(cards):
    ranks = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    is_flush = len(set(suits)) == 1
    uq = sorted(set(ranks), reverse=True)
    is_straight = False; sh = 0
    if len(uq) >= 5:
        for i in range(len(uq)-4):
            if uq[i]-uq[i+4] == 4: is_straight = True; sh = uq[i]; break
    if {12,0,1,2,3} <= set(uq): is_straight = True; sh = sh or 3
    freq = {}
    for r in ranks: freq[r] = freq.get(r,0)+1
    cts = sorted(freq.values(), reverse=True)
    rbf = sorted(freq.keys(), key=lambda r: (freq[r],r), reverse=True)
    if is_straight and is_flush: return (8, 'straight_flush', [sh])
    if cts == [4,1]: return (7, 'quads', rbf)
    if cts == [3,2]: return (6, 'full_house', rbf)
    if is_flush: return (5, 'flush', ranks)
    if is_straight: return (4, 'straight', [sh])
    if cts == [3,1,1]: return (3, 'trips', rbf)
    if cts == [2,2,1]: return (2, 'two_pair', rbf)
    if cts == [2,1,1,1]: return (1, 'pair', rbf)
    return (0, 'high_card', ranks)

def hand_strength_name(hero_cards, board):
    """Human-readable: straight_flush/quads/full_house/flush/straight/trips/two_pair/pair/high_card"""
    return evaluate_best_hand(hero_cards, board)[1] if hero_cards and board else 'unknown'

def is_made_hand(hero_cards, board):
    """Pair or better using at least one hole card."""
    if not hero_cards or len(hero_cards) < 2 or not board: return False
    if hero_cards[0][0] == hero_cards[1][0]: return True  # pocket pair
    for c in hero_cards:
        if c[0] in [b[0] for b in board]: return True  # paired with board
    r, n, _ = evaluate_best_hand(hero_cards, board)
    return r >= 2  # two_pair+ (could be board-driven but still counts)

def classify_draw(hero_cards, board):
    """Returns best draw: nut_fd/fd/oesd/gutshot/bdfd/overcards/none."""
    if not hero_cards or len(hero_cards) < 2 or not board: return 'none'
    hs = [c[1] for c in hero_cards]; bs = [c[1] for c in board]
    sc = {}
    for s in hs+bs: sc[s] = sc.get(s,0)+1
    # Flush draws
    for s in hs:
        if sc.get(s,0) == 4:
            return 'nut_fd' if any(c[0]=='A' and c[1]==s for c in hero_cards) else 'fd'
    # BDFD (flop only)
    if len(board) <= 3:
        for s in hs:
            if sc.get(s,0) == 3: return 'bdfd'
    # Straight draws
    av = sorted(set(RANK_VAL[c[0]] for c in hero_cards+board))
    for i in range(len(av)-3):
        if av[i+3]-av[i] == 3: return 'oesd'
    for i in range(len(av)-3):
        if av[i+3]-av[i] == 4: return 'gutshot'
    # Overcards
    if board:
        bmax = max(RANK_VAL[c[0]] for c in board)
        if sum(1 for c in hero_cards if RANK_VAL[c[0]] > bmax) >= 2: return 'overcards'
    return 'none'

def classify_hand_for_betting(hero_cards, board, street, sizing_pct=None):
    """Classify a Hero bet as value/semi_bluff/pure_bluff.
    
    v7.33 Bug #8 fix: was 'any pair = value' which misclassified polar overbets
    of weak made hands. Now considers (a) made-hand strength relative to BOARD
    high card and (b) sizing context. Polar overbet (>=80% pot) of marginal
    made hand is classified as BLUFF — Hero is leveraging fold equity, not
    value. Examples: 88 turn-jam on K-Q-J board (third pair turning into bluff
    via polar overbet) — was 'value', now 'pure_bluff'.

    Strength buckets (relative to board high card):
      strong   = top pair good kicker+ / overpair / two-pair+ / sets / straights+
      medium   = top pair no kicker
      marginal = middle/bottom pair
      none     = high card / nothing
    """
    if not is_made_hand(hero_cards, board):
        # No made hand — bluff or semi-bluff based on draws
        if street == 'river': return 'pure_bluff'
        draw = classify_draw(hero_cards, board)
        return 'semi_bluff' if draw != 'none' else 'pure_bluff'

    # Made hand — assess strength bucket
    board_ranks = sorted([RANK_VAL[c[0]] for c in board], reverse=True)
    if not board_ranks:
        return 'value'
    board_top = board_ranks[0]
    board_mid = board_ranks[1] if len(board_ranks) >= 2 else 0
    
    # Detect strength
    is_pp = len(hero_cards) == 2 and hero_cards[0][0] == hero_cards[1][0]
    if is_pp:
        pp_rank = RANK_VAL[hero_cards[0][0]]
        if pp_rank > board_top:
            strength = 'strong'  # overpair
        elif pp_rank == board_top:
            strength = 'strong'  # set
        elif pp_rank >= board_mid:
            strength = 'marginal'  # middle pocket pair under board top
        else:
            strength = 'marginal'  # underpair to multiple board cards
    else:
        # Hole cards may pair the board
        hero_paired_ranks = [RANK_VAL[c[0]] for c in hero_cards if c[0] in [b[0] for b in board]]
        if not hero_paired_ranks:
            # No pair — high card only (rare for made_hand=True; could be straight/flush)
            # Defer to draw-style logic — assume strong if true made hand without pair
            strength = 'strong'
        else:
            pair_rank = max(hero_paired_ranks)
            kicker_candidates = [RANK_VAL[c[0]] for c in hero_cards if c[0] not in [b[0] for b in board]]
            kicker = max(kicker_candidates) if kicker_candidates else 0
            if pair_rank == board_top:
                # Top pair — kicker matters
                if kicker >= 9:  # J kicker or better → TPGK+
                    strength = 'strong'
                elif kicker >= 7:  # 9/T kicker → still TPGK-ish
                    strength = 'medium'
                else:
                    strength = 'marginal'  # TPNK
            elif pair_rank == board_mid:
                strength = 'marginal'  # middle pair
            else:
                strength = 'marginal'  # bottom pair
    
    # Now apply sizing-aware logic
    # Polar overbet (>=80% pot) of marginal hand = bluff (relying on FE not value)
    if strength == 'marginal' and sizing_pct is not None and sizing_pct >= 80:
        # Pure bluff at this sizing — third pair betting big has no SDV when called
        return 'pure_bluff'
    
    return 'value'

def classify_board(board_cards):
    if not board_cards or len(board_cards) < 3: return 'unknown'
    flop = board_cards[:3]
    ranks = [RANK_VAL.get(c[0], 0) for c in flop]
    suits = [c[1] for c in flop]
    if len(set(ranks)) < 3: return 'paired'
    if len(set(suits)) == 1: return 'monotone'
    sr = sorted(ranks)
    if all(3 <= r <= 9 for r in sr) and sr[2] - sr[0] <= 4: return 'connected_mid'
    if max(sr) == 12:
        if sr[1] - sr[0] > 2 and sr[2] - sr[1] > 3: return 'dry_ahigh'
        if len(set(suits)) == 3: return 'dry_ahigh'
    broadways = sum(1 for r in sr if r >= 8)
    if broadways >= 2 and len(set(suits)) <= 2: return 'dynamic'
    if max(sr) <= 6: return 'low_dry'
    return 'other'


# ============================================================
# PARSING
# ============================================================

def parse_session(directory):
    files = sorted(Path(directory).glob('GG*.txt'))
    if not files: files = sorted(Path(directory).glob('*.txt'))
    all_hands = []; seen_ids = set(); parse_errors = 0; tournaments = {}
    for fp in files:
        try: text = fp.read_text(encoding='utf-8', errors='replace')
        except Exception as _fe:
            print(f"  ⚠️  Failed to read {fp.name}: {_fe}", file=__import__('sys').stderr)
            parse_errors += 1; continue
        for chunk in re.split(r'\n\n+(?=Poker Hand #)', text):
            if not chunk.strip().startswith('Poker Hand'): continue
            try:
                hand = parse_one_hand(chunk, fp.name)
                if hand and hand['id'] not in seen_ids:
                    seen_ids.add(hand['id'])
                    all_hands.append(hand)
                elif hand and hand['id'] in seen_ids:
                    print(f"  dup: {hand['id']} (skipped)",
                          file=__import__('sys').stderr)
                if hand:
                    tname = hand.get('tournament', 'Unknown')
                    tkey = hand.get('tournament_id') or tname
                    if tkey not in tournaments:
                        tournaments[tkey] = {'tid': hand.get('tournament_id'),
                                             'name': tname, 'hands': [],
                                             'files': set(),
                                             'format': hand.get('format', 'BOUNTY'),
                                             'buyin': hand.get('buyin', 0)}
                    if hand['id'] not in tournaments[tkey]['hands']:
                        tournaments[tkey]['hands'].append(hand['id'])
                    tournaments[tkey]['files'].add(fp.name)
            except Exception as _he:
                # Log which hand failed so parse errors are traceable
                _hid_m = re.search(r'Poker Hand #(\S+)', chunk[:100])
                _hid_str = _hid_m.group(1) if _hid_m else 'unknown'
                print(f"  ⚠️  Parse error on hand {_hid_str} in {fp.name}: "
                      f"{type(_he).__name__}: {_he}", file=__import__('sys').stderr)
                parse_errors += 1
    return all_hands, tournaments, len(files), parse_errors

PARSER_SCHEMA_VERSION = 3  # Increment when hand dict structure OR parse semantics change
# v3 (handover #1): BB-check-played-postflop no longer wipes the board (phantom-board guard).
# Bumping this version invalidates stale parse caches via the schema check in gem_analyzer (the cache
# is force-reparsed when its stored schema_version < this); `--reparse` forces it unconditionally.
# ALWAYS bump this when parse SEMANTICS change, even if the hand-dict keys are unchanged (handover #5).

def parse_one_hand(text, filename=''):
    hand = {}
    m = re.search(r'Poker Hand #(TM\d+)', text)
    if not m: return None
    hand['id'] = m.group(1)
    hand['schema_version'] = PARSER_SCHEMA_VERSION
    # B134 (Ron 2026-05-20): capture the tournament ID — the HH header always
    # carries "Tournament #N". Used to key the tournaments dict so same-named
    # instances stay distinct.
    _tid_m = re.search(r'Tournament #(\d+)', text[:400])
    hand['tournament_id'] = _tid_m.group(1) if _tid_m else None
    tm = re.search(r'GG\d+-\d+ - (.+)\.txt', filename)
    if tm:
        hand['tournament'] = tm.group(1).strip()
    else:
        # v7.30: fall back to extracting from HH text. Prevents 'Unknown' when
        # caller didn't pass a filename or filename doesn't match GG-pattern.
        # HH header looks like: "Tournament #281143333, 11-M: $30 Sunday Bounty King Hold'em No Limit - Level13(...)"
        # Capture the segment between "Tournament #N, " and " Hold'em" / " - Level".
        ttm = re.search(r"Tournament #\d+,\s*(.+?)(?:\s+Hold'em|\s+-\s+Level)", text[:400])
        hand['tournament'] = ttm.group(1).strip() if ttm else 'Unknown'
    fname_lower = filename.lower() + hand['tournament'].lower()
    # v7.15: MYSTERY_BOUNTY tagged distinctly (massive 6-fig mystery prizes shift covering-stack EV)
    if 'mystery bounty' in fname_lower or 'mystery' in fname_lower:
        hand['format'] = 'MYSTERY_BOUNTY'
    elif 'satellite' in fname_lower or 'sat ' in fname_lower:
        hand['format'] = 'SATELLITE'
    elif 'racer' in fname_lower:
        hand['format'] = 'RACER'
    elif 'bounty' in fname_lower or 'bh ' in fname_lower:
        hand['format'] = 'BOUNTY'
    else:
        hand['format'] = 'FREEZEOUT'
    # Batch 1 (0G): Game-type quarantine — detect NLH vs PLO vs ShortDeck.
    # HH header: "Hold'em No Limit" or "Omaha Pot Limit" or "Short Deck".
    # Non-NLH hands get quarantined so Hold'em detectors don't fire on them.
    _header_300 = text[:400].lower()
    if 'omaha' in _header_300 or 'plo' in _header_300:
        hand['game_type'] = 'PLO'
    elif 'short deck' in _header_300 or 'shortdeck' in _header_300 or '6+' in _header_300:
        hand['game_type'] = 'ShortDeck'
    else:
        hand['game_type'] = 'NLH'
    # Buy-in: match "$30" (prefix) or "30 USD" / "30€" / "30$" (postfix)
    bm = re.search(r'(?:\$|€|USD\s*)(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:USD|€|\$)', text[:300])
    if bm:
        hand['buyin'] = float(bm.group(1) or bm.group(2))
    else:
        hand['buyin'] = 0
    # v7.30 P0-1: outer capture must not consume the inner '(' that opens the ante.
    # Was [^)]+ (greedy through inner '('); fixed to [^()]+ so the optional inner group can claim "(150)".
    lm = re.search(r'Level(\d+)\(([^()]+(?:\([^)]*\))?)\)', text)
    if lm:
        hand['level'] = int(lm.group(1))
        blind_str = lm.group(2).replace(',', '')
        bm2 = re.match(r'(\d+)/(\d+)(?:\((\d+)\))?', blind_str)
        if bm2: hand['sb_blind'] = int(bm2.group(1)); hand['bb_blind'] = int(bm2.group(2)); hand['ante'] = int(bm2.group(3)) if bm2.group(3) else 0
        else: hand['sb_blind'] = 1; hand['bb_blind'] = 2; hand['ante'] = 0
    else: hand['level'] = 0; hand['sb_blind'] = 1; hand['bb_blind'] = 2; hand['ante'] = 0
    bb = hand['bb_blind'] if hand['bb_blind'] > 0 else 1

    # Date + time from hand text
    dm = re.search(r'(\d{4}/\d{2}/\d{2})', text)
    hand['hand_ts_date'] = dm.group(1).replace('/', '-') if dm else ''
    # v7.36 (Bug #2 fix): the in-file timestamp is in a non-Hero-local timezone
    # (typically UTC/ET) and rolls into the next calendar day for late-evening
    # play, which mis-attributes the session date. The GG filename prefix
    # `GG{YYYYMMDD}-{HHMM}` reflects Hero's local play-date; prefer it.
    fdm = re.search(r'GG(\d{4})(\d{2})(\d{2})-\d{4}', filename)
    if fdm:
        hand['date'] = f"{fdm.group(1)}-{fdm.group(2)}-{fdm.group(3)}"
    else:
        hand['date'] = hand['hand_ts_date']
    # Time: "2026/04/07 00:00:01" → "00:00:01" captured as hand_time
    tm = re.search(r'\d{4}/\d{2}/\d{2}\s+(\d{2}:\d{2}:\d{2})', text)
    hand['hand_time'] = tm.group(1) if tm else ''

    seats = {}
    for sm in re.finditer(r'Seat (\d+): (\S+) \((\d[\d,]*(?:\.\d+)?)\s+in chips\)', text):
        sn = int(sm.group(1)); seats[sn] = {'player': sm.group(2), 'stack': float(sm.group(3).replace(',', '')), 'stack_bb': float(sm.group(3).replace(',', '')) / bb}
    btn_m = re.search(r'Seat #(\d+) is the button', text)
    btn_seat = int(btn_m.group(1)) if btn_m else 1
    # Table size detection: "Table '18' 8-max" or "6-max" or "5-max"
    # B150 (handover 2026-06-11, orig id B140): the "-max" label is table
    # CAPACITY; with an empty/sitting-out seat it overstates the dealt count
    # and GTOW loads a grid with shifted position labels. Convention now:
    # table_size = DEALT players; capacity preserved as table_capacity.
    table_size_m = re.search(r'(\d+)-max', text[:300])
    seat_nums = sorted(seats.keys()); n_players = len(seat_nums)
    hand['table_capacity'] = (int(table_size_m.group(1)) if table_size_m
                              else n_players)
    hand['table_size'] = n_players
    if n_players < 2: return None
    btn_idx = seat_nums.index(btn_seat) if btn_seat in seat_nums else 0
    ordered = seat_nums[btn_idx:] + seat_nums[:btn_idx]
    pos_names = ['BTN', 'SB', 'BB']
    remaining = n_players - 3
    if remaining >= 6: pos_names += ['UTG', 'UTG+1', 'UTG+2', 'MP', 'HJ', 'CO']
    elif remaining == 5: pos_names += ['UTG', 'UTG+1', 'MP', 'HJ', 'CO']
    elif remaining == 4: pos_names += ['UTG', 'MP', 'HJ', 'CO']  # B28 fix: was ['UTG+1', ...] — at 7-handed, first non-blind is UTG, not UTG+1. _open_chart_pos handles 7-max → 8-max chart shift downstream.
    elif remaining == 3: pos_names += ['MP', 'HJ', 'CO']
    elif remaining == 2: pos_names += ['HJ', 'CO']
    elif remaining == 1: pos_names += ['CO']
    pos_names = pos_names[:n_players]
    if n_players == 2: pos_names = ['BTN', 'BB']
    for i, sn in enumerate(ordered):
        if i < len(pos_names): seats[sn]['position'] = pos_names[i]
    player_position = {info['player']: info.get('position', 'UNK') for sn, info in seats.items()}

    hero_m = re.search(r'Dealt to (\S+) \[([^\]]+)\]', text)
    if not hero_m: return None
    hero_name = hero_m.group(1); hero_cards = hero_m.group(2).split()
    hand['hero'] = hero_name; hand['cards'] = hero_cards
    hero_seat = next((sn for sn, info in seats.items() if info['player'] == hero_name), None)
    if hero_seat is None: return None
    hand['position'] = seats[hero_seat].get('position', 'UNK')
    hand['stack_bb'] = seats[hero_seat]['stack_bb']; hand['n_players'] = n_players
    # SPEC #0: Unified villain identity record — every non-Hero seated player
    hand['villains'] = {}
    for _sn, _si in seats.items():
        if _si['player'] == hero_name:
            continue
        hand['villains'][_si['player']] = {
            'name': _si['player'],
            'seat': _sn,
            'position': _si.get('position', '?'),
            'stack_bb': round(_si.get('stack_bb', 0), 1),
            'shown_cards': None,  # populated after showdown parsing
        }
    # Effective position: normalize to distance from BTN (charts assume 9-ring)
    _pos_dist = {'BTN': 0, 'CO': 1, 'HJ': 2, 'MP': 3, 'UTG+1': 4, 'UTG': 5}
    _dist = _pos_dist.get(hand['position'], -1)
    non_blind = n_players - 2
    if hand['position'] in ('SB', 'BB'):
        hand['eff_pos'] = hand['position']
    elif non_blind <= 4:
        hand['eff_pos'] = ['BTN','CO','HJ','LJ'][min(_dist, 3)]
    elif non_blind <= 5:
        hand['eff_pos'] = ['BTN','CO','HJ','LJ','MP'][min(_dist, 4)]
    elif non_blind <= 6:
        hand['eff_pos'] = ['BTN','CO','HJ','LJ','MP','EP'][min(_dist, 5)]
    else:
        hand['eff_pos'] = ['BTN','CO','HJ','LJ','MP','EP','EP'][min(_dist, 6)]

    streets = {'preflop': '', 'flop': '', 'turn': '', 'river': '', 'showdown': ''}
    current = 'preflop'; board = []
    for line in text.split('\n'):
        if '*** FLOP ***' in line:
            current = 'flop'; fm = re.search(r'\[([^\]]+)\]', line)
            if fm: board = fm.group(1).split()
        elif '*** TURN ***' in line:
            current = 'turn'; fm = re.search(r'\[([^\]]+)\] \[([^\]]+)\]', line)
            if fm: board = fm.group(1).split() + fm.group(2).split()
        elif '*** RIVER ***' in line:
            current = 'river'; fm = re.findall(r'\[([^\]]+)\]', line)
            if len(fm) >= 2: board = fm[0].split() + [fm[1]]
            elif fm: board = fm[0].split()
        elif '*** SHOW DOWN ***' in line or '*** SHOWDOWN ***' in line or '*** SUMMARY ***' in line:
            current = 'showdown'
        streets[current] += line + '\n'
    hand['board'] = board
    hand['board_texture'] = classify_board(board) if len(board) >= 3 else 'none'
    # v7.31: fine-grained GTO archetype (Dave taxonomy, 13 buckets) for
    # GTO-compliance findings. board_texture (10 buckets) preserved unchanged
    # for backwards compat with K4/K6 detectors and Appendix M.
    hand['board_archetype'] = (
        _classify_archetype(board) if len(board) >= 3 else 'unknown'
    )

    # === PREFLOP PARSING ===
    hero_pf_action = 'fold'; hero_raised_pf = False; hero_called_pf = False
    first_in = True; hero_acted = False; villain_jammed_before_hero = False
    pf_raise_count = 0; opener_position = None; hero_faced_raise = False
    pf_pot = hand['sb_blind'] + hand['bb_blind'] + hand['ante'] * n_players
    player_committed = {}
    # v7.25 (J44): track opener's raise amount and Hero's 3-bet amount in chips
    # for IP 3-bet sizing detector. Both stored as raw chip totals; converted
    # to BB ratio after the loop completes.
    opener_raise_to_chips = 0
    hero_3bet_to_chips = 0
    opener_was_hero = False  # if Hero was the opener, no 3-bet sizing to compute

    # A2b-1: Build the action ledger — canonical source of truth for all
    # downstream consumers (appendix, pot-odds, EAI, GTOW, etc.)
    action_ledger = []
    _ledger_line_idx = 0

    pf_sequence = []
    for line in streets['preflop'].split('\n'):
        # v7.30 P0-1b: only blinds enter player_committed (they're part of the betting round).
        # Antes are dead money already counted in pf_pot init via ante×n_players —
        # tracking them in player_committed corrupts later raise-increment math
        # (pf_pot += new_total - prev_commit) by deflating each raise by exactly one ante.
        pm = re.match(r'(\S+): posts (?:small blind|big blind) (\d[\d,]*(?:\.\d+)?)', line)
        if pm: player_committed[pm.group(1)] = player_committed.get(pm.group(1), 0) + float(pm.group(2).replace(',', '')); continue
        # Antes are still recognized so we skip them (otherwise they'd hit the `am` regex below
        # and get misparsed); they don't update any state.
        if re.match(r'\S+: posts the ante \d', line): continue
        am = re.match(r'(\S+): (folds|checks|calls|bets|raises)(.*)', line)
        if not am: continue
        player, action, rest = am.group(1), am.group(2), am.group(3)
        is_allin = 'all-in' in rest.lower() if rest else False
        amount = 0; raise_to = 0
        if rest:
            amt_m = re.search(r'(\d[\d,]*(?:\.\d+)?)', rest)
            if amt_m: amount = float(amt_m.group(1).replace(',', ''))
            to_m = re.search(r'to\s+(\d[\d,]*(?:\.\d+)?)', rest)
            if to_m: raise_to = float(to_m.group(1).replace(',', ''))
        prev_commit = player_committed.get(player, 0)
        if action == 'raises':
            pf_raise_count += 1; new_total = raise_to if raise_to else (prev_commit + amount)
            pf_pot += new_total - prev_commit; player_committed[player] = new_total
            if pf_raise_count == 1:
                opener_position = player_position.get(player, 'UNK')
                # v7.25 (J44): capture opener's raise to-amount in chips
                opener_raise_to_chips = new_total
                if player == hero_name:
                    opener_was_hero = True
            elif pf_raise_count == 2 and player == hero_name:
                # v7.25 (J44): Hero 3-bet — capture to-amount in chips
                hero_3bet_to_chips = new_total
        elif action == 'calls': pf_pot += amount; player_committed[player] = prev_commit + amount
        pos = player_position.get(player, '?')
        tag = '(H)' if player == hero_name else ''
        pf_sequence.append(f"{pos}{tag}:{action}")
        if player == hero_name:
            hero_acted = True
            if action == 'raises':
                hero_raised_pf = True; hero_pf_action = 'raise'
                _hero_raise_number = pf_raise_count  # count AT Hero's raise (after increment)
                if pf_raise_count >= 2: hero_pf_action = '3bet' if pf_raise_count == 2 else '4bet+'
            elif action == 'calls': hero_called_pf = True; hero_pf_action = 'call'
            elif action == 'folds': hero_pf_action = 'fold'
            elif action == 'checks': hero_pf_action = 'check'
        else:
            if not hero_acted:
                if action in ('raises', 'calls'): first_in = False
                if action == 'raises':
                    hero_faced_raise = True
                    if is_allin: villain_jammed_before_hero = True

    # B-AVIEL (2026-06-01): BB walk detection — when everyone folds to the
    # BB, Hero never acts, so pf_action stays at the default 'fold'. This
    # causes push/fold detectors to flag a walk as a "missed push" (the BB
    # literally won +1.3BB by sitting there). Fix: if Hero is BB, had
    # first-in opportunity (no one opened), and pf_action is still the
    # default 'fold' with no VPIP — it's a walk. Set to 'check'.
    if (hero_pf_action == 'fold' and not hero_raised_pf and not hero_called_pf
            and hand.get('position') == 'BB' and first_in):
        hero_pf_action = 'check'
    hand['pf_action'] = hero_pf_action; hand['vpip'] = hero_raised_pf or hero_called_pf
    hand['pfr'] = hero_raised_pf; hand['first_in'] = first_in
    hand['villain_jammed'] = villain_jammed_before_hero; hand['pf_raise_count'] = pf_raise_count
    hand['opener_position'] = opener_position; hand['hero_faced_raise'] = hero_faced_raise

    # v7.25 (J44): compute hero_3bet_size_x ratio for IP 3-bet sizing detector
    # Null when Hero didn't 3-bet, or when Hero was the opener (no 3-bet
    # opportunity), or when opener_raise was zero (parser edge case).
    if (hero_3bet_to_chips > 0
            and opener_raise_to_chips > 0
            and not opener_was_hero
            and bb > 0):
        hand['hero_3bet_size_x'] = round(hero_3bet_to_chips / opener_raise_to_chips, 2)
        hand['hero_3bet_to_bb'] = round(hero_3bet_to_chips / bb, 2)
        hand['opener_raise_to_bb'] = round(opener_raise_to_chips / bb, 2)
    else:
        hand['hero_3bet_size_x'] = None
        hand['hero_3bet_to_bb'] = None
        hand['opener_raise_to_bb'] = None


    # v7.10: Track jammer details + stacks behind Hero for steal/CVJ evaluation
    jammer_stack_bb = 0; jammer_position = ''
    if villain_jammed_before_hero:
        # Find the villain who jammed before Hero acted
        for line in streets['preflop'].split('\n'):
            am = re.match(r'(\S+): raises.*all-in', line, re.IGNORECASE)
            if am and am.group(1) != hero_name:
                jammer_name = am.group(1)
                jammer_position = player_position.get(jammer_name, 'UNK')
                # Get jammer stack from seats
                for sn, info in seats.items():
                    if info['player'] == jammer_name:
                        jammer_stack_bb = info['stack_bb']
                        break
                break
    hand['jammer_stack_bb'] = round(jammer_stack_bb, 1)
    hand['jammer_position'] = jammer_position

    # Stacks behind Hero (for steal evaluation) — players acting AFTER Hero preflop
    stacks_behind = {}
    pos_action_order = ['UTG', 'UTG+1', 'UTG+2', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB']
    hero_pos = hand['position']
    if hero_pos in pos_action_order:
        hero_idx = pos_action_order.index(hero_pos)
        for sn, info in seats.items():
            p = info.get('position', '')
            if p in pos_action_order:
                p_idx = pos_action_order.index(p)
                if p_idx > hero_idx:
                    stacks_behind[p] = round(info['stack_bb'], 1)
    hand['stacks_behind'] = stacks_behind
    # CP22: full per-seat starting stacks (all N seats, not just survivors).
    # Needed by the appendix grid builder so folders' stacks display correctly.
    hand['seat_stacks_bb_all'] = {
        info.get('position', sn): round(info.get('stack_bb', 0), 1)
        for sn, info in seats.items()
        if info.get('position')
    }

    # === eff_stack_bb_at_decision — ONE canonical source (v8.17.1 Iter-1 rev) ===
    # The parser no longer carries its own min-stack algorithm (the v7.48.1 walk +
    # the dead-short threshold are removed). The single canonical owner is
    # gem_decision_snapshot.build_decision_snapshot(); the field is stamped from it
    # AFTER the action_ledger is built (the snapshot replays the ledger to Hero's
    # exact action index). We persist the per-player starting stacks the snapshot
    # needs so every consumer derives effective stacks from the SAME numbers.
    hand['seat_stack_by_player'] = {info['player']: info['stack_bb']
                                    for info in seats.values()}

    hand['hero_3bet'] = hero_raised_pf and hero_faced_raise
    # fold_to_3bet: Hero OPENED (was first raiser), faced 3-bet, folded
    # Exclude: Hero 3-bet then faced 4-bet and folded (that's fold_to_4bet)
    hand['fold_to_3bet'] = (hero_raised_pf and hero_pf_action == 'fold' 
                            and pf_raise_count >= 2 and not hand['hero_3bet'])
    hand['fold_to_4bet'] = (hand['hero_3bet'] and hero_pf_action == 'fold' 
                            and pf_raise_count >= 3)
    hand['pf_sequence'] = pf_sequence

    # Squeeze: Hero 3-bet after open + cold call (call before Hero's raise).
    # v7.32 (C7): also compute squeeze_opp independent of Hero's action — i.e.
    # "Hero faced an open + at least one cold-caller before Hero's first PF
    # action." This is the denominator for squeeze_pct_by_pos.
    # v8.5.1 (B158): tightened — must be exactly one raise (the open) + at least
    # one cold-call, not multi-raise pots. Also excludes push/fold stacks (<8BB)
    # and Hero in EP (UTG/UTG+1) where squeezing is unrealistic.
    had_caller_before_hero_first = False
    saw_open_pre_hero = False
    _n_raises_pre_hero = 0
    for line in streets['preflop'].split('\n'):
        am = re.match(r'(\S+): (folds|checks|calls|raises)', line)
        if not am: continue
        if am.group(1) == hero_name: break
        if am.group(2) == 'raises':
            _n_raises_pre_hero += 1
            saw_open_pre_hero = True
        elif am.group(2) == 'calls' and saw_open_pre_hero:
            had_caller_before_hero_first = True
    _is_squeeze_structure = (saw_open_pre_hero and had_caller_before_hero_first
                             and _n_raises_pre_hero == 1
                             and hand.get('position', '') not in ('UTG', 'UTG+1')
                             and hand.get('stack_bb', 0) >= 8)
    hand['squeeze_opp'] = _is_squeeze_structure
    hand['is_squeeze'] = hand['hero_3bet'] and had_caller_before_hero_first

    # v7.34: BB facing SB limp (Jasper exploit #2 — "raise SB open limp").
    # Pattern: Hero in BB, no preflop raises, all earlier players folded,
    # SB called (limped) → Hero acts. Hero's options are check (take flop)
    # or raise (iso). Pure print spot per Jasper because GG MTT pool
    # under-3bets, so isos rarely face resistance and limp ranges are weak.
    #
    # Edge cases:
    #   • HU (n_players=2): pf_sequence is just [SB:..., BB(H):...] —
    #     "all earlier folded" check trivially passes. Counts.
    #   • SB jams open (raise+all-in): pf_raise_count >= 1, gate excludes.
    #   • SB limp/3-bets after Hero iso: Hero's pf_action becomes 'fold' or
    #     '3bet' depending; bb_faced_sb_limp still True (denom), but
    #     bb_iso/checked tracks Hero's *first* action (raise→iso, check→take).
    hand['bb_faced_sb_limp'] = False
    hand['bb_iso_sb_limp'] = False
    hand['bb_checked_sb_limp'] = False
    if hand.get('position') == 'BB':
        # Find SB action in pf_sequence. Format: "POS[(H)]:action"
        sb_idx = None
        for i, item in enumerate(pf_sequence):
            pos_part = item.split(':', 1)[0]
            if pos_part == 'SB':  # SB is non-Hero (Hero is BB → never has (H) on SB)
                sb_idx = i
                break
        if sb_idx is not None:
            # Everyone before SB must have folded (no opens, no calls)
            before_sb = pf_sequence[:sb_idx]
            all_folded_before_sb = all(':folds' in x for x in before_sb)
            sb_action = pf_sequence[sb_idx].split(':', 1)[1]
            if all_folded_before_sb and sb_action == 'calls':
                hand['bb_faced_sb_limp'] = True
                # Hero's first preflop action determines iso vs check.
                # pf_action captures Hero's FINAL action; for the iso
                # detection we want the FIRST action. Walk pf_sequence
                # for the first BB(H) entry.
                for item in pf_sequence:
                    if '(H)' in item.split(':', 1)[0]:
                        first_action = item.split(':', 1)[1]
                        if first_action == 'raises':
                            hand['bb_iso_sb_limp'] = True
                        elif first_action == 'checks':
                            hand['bb_checked_sb_limp'] = True
                        break

    # v7.31 Patch 6: live-player count at the moment of Hero's final preflop action.
    # Used by V15c gate to distinguish "pot was MW at some point but HU at call"
    # (HU — V15c should NOT fire) vs "still 3+ live when Hero called" (true MW — V15c fires).
    # Walk pf_sequence; track who's folded by counting 'folds' actions (each folder
    # appears exactly once with action='folds'). Live count = dealt_in - folds_so_far.
    pf_lines = streets['preflop'].split('\n')
    hero_action_indices = []  # line indices where Hero acted
    for i, line in enumerate(pf_lines):
        am = re.match(r'(\S+): (folds|checks|calls|bets|raises)', line)
        if am and am.group(1) == hero_name:
            hero_action_indices.append(i)
    if hero_action_indices:
        last_hero_idx = hero_action_indices[-1]
        # Count folds at or before last_hero_idx (folds that already happened
        # by the time Hero made the final action — Hero's own action itself
        # is at last_hero_idx and isn't a fold here)
        folds_before_or_at_hero = sum(
            1 for i, line in enumerate(pf_lines)
            if i <= last_hero_idx and ': folds' in line
        )
        live_at_hero_final = n_players - folds_before_or_at_hero
        hand['mw_at_hero_final_pf_action'] = live_at_hero_final >= 3
    else:
        hand['mw_at_hero_final_pf_action'] = False

    # v7.31 Patch 6: did Hero face a flop bet/raise before having a chance to act?
    # Used by J14 gate — J14 (Monotone IP No CBet) assumes Hero had the c-bet option.
    # When villain donk-leads or check-raises before Hero's first flop action,
    # there's no "no c-bet" decision to flag.
    flop_lines = streets.get('flop', '').split('\n')
    hero_faced_prior_flop_bet = False
    for line in flop_lines:
        am = re.match(r'(\S+): (folds|checks|calls|bets|raises)', line)
        if not am: continue
        actor, act = am.group(1), am.group(2)
        if actor == hero_name:
            break  # reached Hero's first flop action
        if act in ('bets', 'raises'):
            hero_faced_prior_flop_bet = True
            break
    hand['hero_faced_prior_flop_bet'] = hero_faced_prior_flop_bet

    # Players at flop
    flop_folds = sum(1 for line in streets['preflop'].split('\n') if ': folds' in line)
    hand['players_at_flop'] = n_players - flop_folds if len(board) >= 3 else 0

    # Effective stack (min of Hero + shortest active villain at flop)
    if hand['players_at_flop'] >= 2:
        active_stacks = []
        for sn, info in seats.items():
            if sn == hero_seat: continue
            p = info['player']
            # Check if player folded preflop
            folded = any(p in line and ': folds' in line for line in streets['preflop'].split('\n'))
            if not folded: active_stacks.append(info['stack_bb'])
        hand['eff_stack_bb'] = min(hand['stack_bb'], min(active_stacks)) if active_stacks else hand['stack_bb']
    else:
        hand['eff_stack_bb'] = hand['stack_bb']

    # SPR at flop
    if hand['players_at_flop'] >= 2 and pf_pot > 0:
        remaining_stack = (hand['eff_stack_bb'] * bb - player_committed.get(hero_name, 0))
        hand['spr'] = round(remaining_stack / pf_pot, 1) if pf_pot > 0 else 0
    else:
        hand['spr'] = 0

    # === POSTFLOP PARSING ===
    def _river_bet_is_value(hc, bd):
        # v8.12.4 (QA item 11, TM6060338193 K9 on QQQ-6-2): is_made_hand()
        # credited "Value Bet" whenever the BOARD supplied a made hand. A
        # river bet only counts as value when Hero's hole cards beat playing
        # the board — and a kicker-only improvement on a pair-type board
        # class (trips/two-pair on board + unpaired hole cards) is a
        # thin/bluffy bet, not a value bet.
        if not is_made_hand(hc, bd):
            return False
        if len(bd) >= 5:
            try:
                hr = evaluate_best_hand(hc, bd)
                br = evaluate_best_hand(bd[3:5], bd[:3])  # board plays itself
                if hr <= br:
                    return False  # plays the board (or worse)
                if hr[0] == br[0] and hr[0] in (1, 2, 3, 7):
                    return False  # kicker-only upgrade on a paired board
            except Exception:
                pass
        return True

    hand['hero_bets'] = []; hand['facing_bets'] = []; hand['river_action'] = None
    hand['check_raises'] = []; hero_bet_streets = set()
    pot = pf_pot; hero_is_pfr = hero_raised_pf
    hero_pos_val = {'BTN': 6, 'CO': 5, 'HJ': 4, 'MP': 3, 'UTG+1': 2, 'UTG': 1, 'SB': 0, 'BB': 0}
    # A1 (Aviel handoff 2026-05-25): hero_ip was derived purely from Hero's
    # ABSOLUTE seat rank (HJ/CO/BTN -> IP). That is wrong whenever the actual
    # opponent sits later than Hero — exactly the open-then-3bet-caller case
    # (Hero opens HJ, CO 3-bets, Hero calls -> Hero is OOP postflop). Derive
    # hero_ip from the ACTUAL flop action order instead: the player who acts
    # LAST on the flop is in position. Hero is IP iff Hero is the last
    # distinct actor on the flop. Fall back to the absolute-seat heuristic
    # only when the flop has no parseable action (e.g. all-in preflop, board
    # runs out).
    _flop_txt = streets.get('flop', '') if isinstance(streets, dict) else ''
    _flop_actors_order = []
    for _ln in _flop_txt.split('\n'):
        _am = re.match(r'(\S+): (folds|checks|calls|bets|raises)', _ln)
        if _am:
            _who = _am.group(1)
            if _who not in _flop_actors_order:
                _flop_actors_order.append(_who)
    if _flop_actors_order:
        hero_ip = (_flop_actors_order[-1] == 'Hero')
    else:
        hero_ip = hero_pos_val.get(hand['position'], 3) >= 4
    hand['hero_ip'] = hero_ip
    # Keep the absolute-seat value available under a clearly-named field for
    # any consumer that genuinely wants nominal late position.
    hand['hero_late_position'] = hero_pos_val.get(hand['position'], 3) >= 4

    villain_bet_flop_first = False  # did villain bet before Hero on flop?
    flop_allin = False  # did anyone go all-in on flop?
    hero_check_raised_flop = False
    villain_folded_to_flop_cbet = False
    hero_bet_river_after_check_turn = False
    hero_street_actions = {}  # LINE TRACKER: {street: action}
    # v7.27 NEW tracking — needed for fold-to-XR / donk metrics that can't be
    # derived from facing_bets alone (facing_bets only logs Hero call/fold,
    # not Hero raise responses; donk needs first-action context)
    villain_raised_hero_cbet_flop = False
    hero_donked_flop = False
    hero_donked_turn = False
    # v7.28 NEW tracking — per-street villain check-raise detection
    # (distinct from v7.27 'villain raised after Hero c-bet' which fires on
    # ANY raise after a c-bet; v7.28 specifically detects "villain checked,
    # then raised Hero's bet" — strict check-raise pattern, all 3 streets)
    villain_xr_by_street = {'flop': False, 'turn': False, 'river': False}
    # Track whether Hero bet "into a check" (no villain bet before Hero's bet
    # on this street) so we can label a subsequent villain raise as a true XR
    hero_bet_into_check_by_street = {'flop': False, 'turn': False, 'river': False}

    for street_name in ['flop', 'turn', 'river']:
        st = streets[street_name]
        if not st.strip(): continue
        checked_to_hero = True; villain_bet_amount = 0; pot_before_villain_bet = pot
        hero_checked_this_street = False
        for line in st.split('\n'):
            am = re.match(r'(\S+): (folds|checks|calls|bets|raises)(.*)', line)
            if not am: continue
            player, action, rest = am.group(1), am.group(2), am.group(3)
            is_allin = 'all-in' in rest.lower() if rest else False
            amount = 0; raise_to = 0
            if rest:
                amt_m = re.search(r'(\d[\d,]*(?:\.\d+)?)', rest)
                if amt_m: amount = float(amt_m.group(1).replace(',', ''))
                to_m = re.search(r'to\s+(\d[\d,]*(?:\.\d+)?)', rest)
                if to_m: raise_to = float(to_m.group(1).replace(',', ''))
            if is_allin and street_name == 'flop': flop_allin = True
            if player != hero_name:
                if action == 'bets':
                    checked_to_hero = False; pot_before_villain_bet = pot; villain_bet_amount = amount; pot += amount
                    if street_name == 'flop': villain_bet_flop_first = True
                elif action == 'raises':
                    checked_to_hero = False; pot_before_villain_bet = pot; villain_bet_amount = raise_to or amount; pot += raise_to or amount
                    if street_name == 'flop': villain_bet_flop_first = True
                    # v7.27: detect villain raising AFTER Hero's flop cbet (XR or IP raise)
                    if street_name == 'flop' and 'flop' in hero_bet_streets and hero_is_pfr:
                        villain_raised_hero_cbet_flop = True
                    # v7.28: per-street strict check-raise detection
                    # (Hero bet into a check earlier this street, villain now raises)
                    if hero_bet_into_check_by_street.get(street_name):
                        villain_xr_by_street[street_name] = True
                elif action == 'calls': pot += amount
                elif action == 'folds':
                    if street_name == 'flop' and 'flop' in hero_bet_streets: villain_folded_to_flop_cbet = True
            else:
                if action == 'bets':
                    size_pct = (amount / pot * 100) if pot > 0 else 0
                    spot = 'cbet' if hero_is_pfr and street_name == 'flop' else 'barrel' if hero_is_pfr else 'probe'
                    hand['hero_bets'].append((street_name, round(size_pct, 1), spot, 'IP' if hero_ip else 'OOP'))
                    hero_bet_streets.add(street_name); pot += amount
                    # v7.27: donk = Hero (caller, OOP) bets first action of street
                    if (not hero_is_pfr and not hero_ip and not hero_checked_this_street
                            and checked_to_hero):
                        if street_name == 'flop': hero_donked_flop = True
                        elif street_name == 'turn': hero_donked_turn = True
                    # v7.28: track if Hero bet into a check (no prior villain bet this street)
                    # so subsequent villain raise can be labeled as true XR
                    if checked_to_hero:
                        hero_bet_into_check_by_street[street_name] = True
                    if street_name == 'river':
                        hand['river_action'] = 'value_bet' if _river_bet_is_value(hero_cards, board) else 'bluff'
                        if 'turn' not in hero_bet_streets: hero_bet_river_after_check_turn = True
                elif action == 'raises':
                    rtotal = raise_to or amount; size_pct = (rtotal / pot * 100) if pot > 0 else 0
                    spot = 'raise' if villain_bet_amount > 0 else ('cbet' if hero_is_pfr and street_name == 'flop' else 'barrel' if hero_is_pfr else 'probe')
                    hand['hero_bets'].append((street_name, round(size_pct, 1), spot, 'IP' if hero_ip else 'OOP'))
                    hero_bet_streets.add(street_name); pot += rtotal
                    if hero_checked_this_street and villain_bet_amount > 0: hand['check_raises'].append(street_name)
                    if street_name == 'flop' and hero_checked_this_street: hero_check_raised_flop = True
                    # B44 (v7.51, Ron 2026-05-18): when Hero raises a villain bet,
                    # capture the villain lead size as % of pot. Used downstream
                    # to detect capped-range exploit raises (tiny donk lead =>
                    # P6-BluffOverbet detector should skip flag).
                    if villain_bet_amount > 0 and pot_before_villain_bet > 0:
                        hand.setdefault('hero_raise_villain_lead_pct', {})[street_name] = (
                            round(villain_bet_amount / pot_before_villain_bet * 100, 1))
                    if street_name == 'river':
                        hand['river_action'] = 'value_bet' if _river_bet_is_value(hero_cards, board) else 'bluff'
                elif action == 'calls':
                    if villain_bet_amount > 0 and pot_before_villain_bet > 0:
                        hand['facing_bets'].append((street_name, round(villain_bet_amount / pot_before_villain_bet * 100, 1), 'call'))
                    pot += amount
                    if street_name == 'river': hand['river_action'] = 'call'
                elif action == 'folds':
                    if villain_bet_amount > 0 and pot_before_villain_bet > 0:
                        hand['facing_bets'].append((street_name, round(villain_bet_amount / pot_before_villain_bet * 100, 1), 'fold'))
                    if street_name == 'river': hand['river_action'] = 'fold_to_bet'
                elif action == 'checks':
                    hero_checked_this_street = True
                    if street_name == 'river' and checked_to_hero:
                        hand['river_action'] = 'check_sdv' if is_made_hand(hero_cards, board) else 'check_giveup'

    hand['villain_bet_flop_first'] = villain_bet_flop_first
    hand['flop_allin'] = flop_allin
    hand['hero_check_raised_flop'] = hero_check_raised_flop
    hand['villain_folded_to_flop_cbet'] = villain_folded_to_flop_cbet
    # v7.27 persisted tracking
    hand['villain_raised_hero_cbet_flop'] = villain_raised_hero_cbet_flop
    hand['hero_donked_flop'] = hero_donked_flop
    hand['hero_donked_turn'] = hero_donked_turn
    # v7.28 persisted tracking — per-street villain check-raise + hero bet-raise
    hand['villain_xr_flop'] = villain_xr_by_street['flop']
    hand['villain_xr_turn'] = villain_xr_by_street['turn']
    hand['villain_xr_river'] = villain_xr_by_street['river']
    # populated by second loop below
    hero_action_flags = {st: {'bet': False, 'raise': False, 'call': False,
                              'fold': False, 'check': False}
                         for st in ('flop', 'turn', 'river')}

    # === LINE CLASSIFICATION ===
    # Build per-street action from hero_bets, facing_bets, check_raises
    # v7.15 FIX: distinguish Hero-initiated all-in ('jam'/'xr-ai') from Hero-calling-allin ('callAI'/'xc-ai')
    # v7.15.1 FIX: suppress phantom 'x' when street has no action lines (villains all-in PF, board runs out)
    for street_name2 in ['flop', 'turn', 'river']:
        st2 = streets[street_name2]
        if not st2.strip(): continue
        hero_did_check = False; hero_did_bet = False; hero_did_call = False
        hero_did_fold = False; hero_did_raise = False; villain_did_bet = False
        hero_initiated_allin = False  # v7.15: Hero bet/raised all-in
        hero_called_allin = False     # v7.15: Hero called an all-in
        action_lines_found = 0        # v7.15.1: count actual action lines
        for line2 in st2.split('\n'):
            am2 = re.match(r'(\S+): (folds|checks|calls|bets|raises)(.*)', line2)
            if not am2: continue
            action_lines_found += 1
            p2, a2, r2 = am2.group(1), am2.group(2), am2.group(3)
            ai2 = 'all-in' in r2.lower() if r2 else False
            if p2 == hero_name:
                if a2 == 'checks': hero_did_check = True
                elif a2 == 'bets':
                    hero_did_bet = True
                    if ai2: hero_initiated_allin = True
                elif a2 == 'raises':
                    hero_did_raise = True
                    if ai2: hero_initiated_allin = True
                elif a2 == 'calls':
                    hero_did_call = True
                    if ai2: hero_called_allin = True
                elif a2 == 'folds': hero_did_fold = True
            elif a2 in ('bets', 'raises'): villain_did_bet = True

        # v7.15.1: No action on street = pot settled preflop (villains all-in), skip
        if action_lines_found == 0:
            continue  # don't add phantom 'x' to hero_street_actions

        # v7.28: capture per-street hero action flags for downstream metrics
        # (bet-raise, check-raise responses)
        hero_action_flags[street_name2] = {
            'bet': hero_did_bet, 'raise': hero_did_raise,
            'call': hero_did_call, 'fold': hero_did_fold,
            'check': hero_did_check,
        }

        # Classify the street action
        # v7.15: Hero-initiated all-in = 'jam' (aggressive) or 'xr-ai' (check-raise allin)
        #        Hero-called all-in = 'callAI'/'xc-ai' (bluffcatch/stack-off-callee)
        if hero_initiated_allin:
            if hero_did_check and hero_did_raise:
                act = 'xr-ai'   # check-raise all-in (aggressive)
            else:
                act = 'jam'     # bet/raise all-in (aggressive)
        elif hero_called_allin:
            if hero_did_check:
                act = 'xc-ai'   # check-call all-in (bluffcatch / stack-off callee)
            # B253: bet-then-call-allin (Hero bet, villain jammed, Hero called)
            elif hero_did_bet:
                act = 'bet-callAI'
            else:
                act = 'callAI'  # call all-in (bluffcatch / stack-off callee)
        elif hero_did_check and hero_did_raise:
            act = 'xr'  # check-raise
        elif hero_did_check and hero_did_call:
            act = 'xc'  # check-call
        elif hero_did_check and hero_did_fold:
            act = 'xf'  # check-fold
        elif hero_did_check and not villain_did_bet:
            act = 'x'   # check through
        # B253 (split-verdict): bet-then-call-raise or bet-then-fold composite
        # actions. When Hero bet and then called a raise (or folded to one),
        # these are TWO separate decisions with potentially opposite verdicts.
        elif hero_did_bet and hero_did_call:
            act = 'bet-call'  # bet then called a raise
        elif hero_did_bet and hero_did_fold:
            act = 'bet-fold'  # bet then folded to a raise
        elif hero_did_bet and street_name2 == 'flop' and hero_is_pfr:
            act = 'cbet'
        elif hero_did_bet:
            act = 'bet'
        elif hero_did_raise:
            act = 'raise'
        elif hero_did_call:
            act = 'call'
        elif hero_did_fold:
            act = 'fold'
        else:
            act = 'x'
        hero_street_actions[street_name2] = act

    # Build full line: Role_PotType_Position_actions
    role = 'PFR' if hero_is_pfr else 'Caller'
    pot_type = 'SRP' if hand.get('pf_raise_count', 0) <= 1 else '3BP' if hand.get('pf_raise_count', 0) == 2 else '4BP'
    pos_bucket = 'IP' if hero_ip else 'OOP'
    line_parts = [hero_street_actions.get(s, '') for s in ['flop', 'turn', 'river'] if hero_street_actions.get(s)]
    line_str = '-'.join(line_parts) if line_parts else 'preflop_only'
    
    # Append outcome
    # (outcome added after net_bb is computed, see below)
    hand['line_actions'] = line_str
    hand['pot_type'] = pot_type
    hand['hero_street_actions'] = hero_street_actions
    # v7.28: per-street hero action flags for bet-raise / xr-response derivation
    hand['hero_action_flags'] = hero_action_flags

    # One-and-Done: c-bet flop, checked turn. Exclude: check-raises, all-ins, villain folded flop
    hand['one_and_done'] = ('flop' in hero_bet_streets and 'turn' not in hero_bet_streets
        and hero_is_pfr and len(board) >= 4
        and not hero_check_raised_flop and not flop_allin
        and not villain_folded_to_flop_cbet
        and not hero_bet_river_after_check_turn)

    # Hand strength classification (full evaluator)
    if len(board) >= 3:
        hand['hand_strength'] = hand_strength_name(hero_cards, board)
        hand['draw_type'] = classify_draw(hero_cards, board[:3])  # draw on flop
    else:
        hand['hand_strength'] = 'unknown'; hand['draw_type'] = 'none'

    # Missed river value bet opportunity (FILTERED v7.2):
    # Only flag: TPTK/TPGK+, overpair, 2P+ (real, not board-driven), trips+
    # DON'T flag: TPOK/TPWK (what worse calls?), board-driven two-pair,
    #             3rd pair with 2 streets, MW with weak, draw-completing rivers
    hand['missed_river_value'] = False
    if hand.get('river_action') == 'check_sdv' and len(board) >= 5:
        value_streets = sum(1 for b in hand['hero_bets'] if b[0] in ('flop','turn') and b[2] != 'raise')
        if is_made_hand(hero_cards, board):
            rank, name, _ = evaluate_best_hand(hero_cards, board)
            is_strong_enough = False
            
            if rank >= 3:  # trips+ always flag
                is_strong_enough = True
            elif rank == 2:  # two_pair
                # Only flag if BOTH hole cards pair the board (real two-pair)
                # Not if board has two pair and Hero just plays it
                hero_paired = sum(1 for c in hero_cards if c[0] in [b[0] for b in board])
                is_strong_enough = hero_paired >= 2
            elif rank == 1:  # pair
                board_ranks_sorted = sorted([RANK_VAL[c[0]] for c in board], reverse=True)
                # Determine if top pair
                hero_pair_ranks = [RANK_VAL[c[0]] for c in hero_cards if c[0] in [b[0] for b in board]]
                if hero_cards[0][0] == hero_cards[1][0]:  # pocket pair
                    pp_rank = RANK_VAL[hero_cards[0][0]]
                    is_strong_enough = pp_rank >= board_ranks_sorted[0]  # overpair
                elif hero_pair_ranks:
                    pair_rank = max(hero_pair_ranks)
                    if pair_rank >= board_ranks_sorted[0]:  # top pair
                        # Check kicker quality — only flag with GOOD kicker (T+)
                        kicker = max(RANK_VAL[c[0]] for c in hero_cards if c[0] not in [b[0] for b in board])
                        is_strong_enough = kicker >= 8  # T=8, J=9, Q=10, K=11, A=12
                        # TPGK+ (good kicker = T or higher)
                    # 2nd pair or worse = never flag
            
            # 2nd pair with 2 streets = enough
            if not is_strong_enough and value_streets >= 2:
                pass  # don't flag
            elif not is_strong_enough and hand.get('players_at_flop', 0) >= 3:
                pass  # don't flag MW with weak
            elif is_strong_enough and value_streets <= 1:
                # Check if draw completed on river (4-flush or 4-straight on board)
                river_card = board[4]
                river_suit = river_card[1]
                board_suits = [c[1] for c in board]
                four_flush = sum(1 for s in board_suits if s == river_suit) >= 4
                board_vals = sorted([RANK_VAL[c[0]] for c in board])
                # v7.33 Bug #6 fix: dedupe board ranks before four_straight check.
                # Old check on board_vals with duplicates incorrectly flagged paired
                # boards as four-straight (e.g. 5-9-8-T-T → board_vals [3,6,7,8,8],
                # then board_vals[4]-board_vals[1]=8-6=2≤4 is True even though the
                # distinct ranks are 5,8,9,T spanning 5 — no 4-straight possible).
                # This caused real trips/two-pair on paired boards to never get the
                # missed-river-value flag.
                distinct_vals = sorted(set(board_vals))
                four_straight = any(distinct_vals[i+3] - distinct_vals[i] <= 4
                                     for i in range(len(distinct_vals)-3)) \
                                if len(distinct_vals) >= 4 else False
                # Also check if board has 3+ broadways (scary texture)
                broadways_on_board = sum(1 for c in board if RANK_VAL[c[0]] >= 8)
                if not four_flush and not four_straight:
                    # For TP with good kicker, also check board isn't super scary
                    if rank == 1 and broadways_on_board >= 4:
                        pass  # 4+ broadways = too many better hands possible
                    else:
                        hand['missed_river_value'] = True

    # Missed probe opportunity (FILTERED):
    # HU only, IP non-PFR, PFR checked (not bet), Hero checked behind with equity
    hand['missed_probe'] = False
    if (not hero_is_pfr and len(board) >= 4 and hand['vpip']
        and hero_ip and hand.get('players_at_flop', 0) == 2
        and 'flop' not in hero_bet_streets
        and not villain_bet_flop_first):  # villain must have checked, not bet
        if is_made_hand(hero_cards, board[:3]) or classify_draw(hero_cards, board[:3]) in ('nut_fd','fd','oesd'):
            # Also exclude if Hero folded on flop (can't probe if folded)
            hero_folded_flop = any(b[0] == 'flop' and b[2] == 'fold' for b in hand.get('facing_bets', []))
            if not hero_folded_flop:
                hand['missed_probe'] = True

    # Showdown — Hero must have showed cards in SUMMARY
    summary = text.split('*** SUMMARY ***')[1] if '*** SUMMARY ***' in text else ''
    hand['went_to_sd'] = bool(re.search(rf'{re.escape(hero_name)}.*showed', summary))

    # SPEC #1: Parse villain shown cards from showdown + summary sections
    _sd_text = streets.get('showdown', '') + '\n' + summary
    for _sd_m in re.finditer(r'(\S+): shows \[([^\]]+)\]', _sd_text):
        _sd_player = _sd_m.group(1)
        _sd_cards = _sd_m.group(2).split()
        if _sd_player != hero_name and _sd_player in hand.get('villains', {}):
            hand['villains'][_sd_player]['shown_cards'] = _sd_cards
    # Also parse "showed [Xx Xx]" from summary (GG format)
    for _sd_m2 in re.finditer(r'(\S+) showed \[([^\]]+)\]', _sd_text):
        _sd_player2 = _sd_m2.group(1)
        _sd_cards2 = _sd_m2.group(2).split()
        if _sd_player2 != hero_name and _sd_player2 in hand.get('villains', {}):
            if not hand['villains'][_sd_player2].get('shown_cards'):
                hand['villains'][_sd_player2]['shown_cards'] = _sd_cards2

    # SPEC #0: primary_villain — whoever Hero's key decision was against
    # Default: the opener (most common). Override for squeezes/jams below.
    _pv_name = None
    _pv_role = 'opener'
    if opener_position:
        _op_name = next((v['name'] for v in hand.get('villains', {}).values()
                         if v.get('position') == opener_position), None)
        if _op_name:
            _pv_name = _op_name
    # Override: if villain jammed, the jammer is the primary villain
    if hand.get('villain_jammed') and hand.get('jammer_position'):
        _jam_name = next((v['name'] for v in hand.get('villains', {}).values()
                          if v.get('position') == hand['jammer_position']), None)
        if _jam_name:
            _pv_name = _jam_name
            _pv_role = 'jammer'
    hand['primary_villain'] = {'name': _pv_name or '', 'role': _pv_role}

    # SPEC #0: matchups — hand-specific combat data (separate from identity)
    hand['matchups'] = {}
    if hand.get('went_to_sd'):
        for _vn, _vi in hand.get('villains', {}).items():
            if _vi.get('shown_cards'):
                hand['matchups'][_vn] = {
                    'hero_cards': hero_cards,
                    'villain_cards': _vi['shown_cards'],
                    'villain_position': _vi.get('position', '?'),
                }

    # v7.15.1 FIX: pf_allin means Hero committed all chips preflop OR called
    # a preflop all-in where the pot was settled preflop (no further betting).
    # CP20-BUG-1: "Hero: calls N" without "all-in" on Hero's line is still an
    # all-in for equity purposes when a villain jammed and the pot settled.
    # The equity pass must include these hands or the narrative falls back to 0%.
    _hero_allin_line = any(hero_name in line and 'all-in' in line.lower()
                           for line in streets['preflop'].split('\n') if ': ' in line)
    any_pf_allin = any('all-in' in line.lower()
                       for line in streets['preflop'].split('\n') if ': ' in line)
    postflop_has_action = False
    for street_name3 in ['flop', 'turn', 'river']:
        st3 = streets.get(street_name3, '')
        if any(re.match(r'\S+: (folds|checks|calls|bets|raises)', l) for l in st3.split('\n')):
            postflop_has_action = True
            break
    pf_settled = any_pf_allin and not postflop_has_action
    # Hero is "preflop all-in" if:
    # (a) Hero's own line says "all-in" (the jammer), OR
    # (b) a villain went all-in preflop AND the pot settled preflop AND Hero
    #     called (Hero committed all meaningful chips even if Hero has a
    #     residual side-pot stack — the equity confrontation is real)
    _hero_called_jam = (any_pf_allin and hero_called_pf and pf_settled)
    pf_allin = _hero_allin_line or _hero_called_jam
    hand['pf_allin'] = pf_allin
    hand['pf_settled'] = pf_settled

    # Net result — use COMMITTED chips, not starting stack
    collected = sum(float(cm.group(1).replace(',', '')) for cm in re.finditer(rf'{re.escape(hero_name)} collected (\d[\d,]*(?:\.\d+)?)', text))
    # BUG FIX v7.2: "Uncalled bet (X) returned to Hero" must be counted for net_bb
    # but NOT for the 'won' flag — returning excess chips doesn't mean Hero won
    returned = sum(float(rm.group(1).replace(',', '')) for rm in re.finditer(r'Uncalled bet \((\d[\d,]*(?:\.\d+)?)\) returned to ' + re.escape(hero_name), text))
    # DO NOT add returned to collected — collected stays as pot winnings only
    # Total committed = preflop committed + all postflop bets/calls/raises
    hero_committed = player_committed.get(hero_name, 0)
    for b in hand['hero_bets']:
        # b = (street, size_pct, spot, ip) — need raw amount
        pass  # hero_bets has percentages not amounts, need to get from raw
    # Better: parse all Hero money actions from raw text
    hero_committed = 0
    for line in text.split('\n'):
        if hero_name not in line: continue
        # Posts (blinds/antes)
        pm = re.match(rf'{re.escape(hero_name)}: posts (?:small blind|big blind|the ante) (\d[\d,]*(?:\.\d+)?)', line)
        if pm: hero_committed += float(pm.group(1).replace(',', '')); continue
        # Calls
        cm2 = re.match(rf'{re.escape(hero_name)}: calls (\d[\d,]*(?:\.\d+)?)', line)
        if cm2: hero_committed += float(cm2.group(1).replace(',', '')); continue
        # Bets
        bm = re.match(rf'{re.escape(hero_name)}: bets (\d[\d,]*(?:\.\d+)?)', line)
        if bm: hero_committed += float(bm.group(1).replace(',', '')); continue
        # Raises — committed amount is raise_to minus previous committed this round
        rm = re.match(rf'{re.escape(hero_name)}: raises.*?to (\d[\d,]*(?:\.\d+)?)', line)
        if rm:
            raise_to = float(rm.group(1).replace(',', ''))
            # For raises, the total committed becomes raise_to (in that round)
            # But we've already counted earlier calls/posts, so add the difference
            # Actually simpler: raises "to X" means Hero's total in this betting round is X
            # We need to not double-count. Let's use a different approach.
            pass

    # Cleaner approach: compute from raw text by finding uncalled bet returns
    # hero_net = collected + returned - total_put_in
    # But simplest correct: collected > 0 means Hero won the pot
    # If Hero won: net = collected - what_hero_put_in
    # If Hero lost/folded: net = -what_hero_put_in

    # Reparse committed properly using running total per betting round
    # B253 (split-verdict): also track per-street per-node committed amounts
    # so that bet-then-call-raise patterns can be attributed correctly.
    hero_committed = 0
    current_round_committed = 0
    _current_street = 'preflop'
    _street_nodes = {}           # street → list of {'action': str, 'amount': float}
    _hero_bet_this_street = False
    for line in text.split('\n'):
        line = line.strip()
        if '*** FLOP ***' in line:
            _current_street = 'flop'; current_round_committed = 0; _hero_bet_this_street = False
        elif '*** TURN ***' in line:
            _current_street = 'turn'; current_round_committed = 0; _hero_bet_this_street = False
        elif '*** RIVER ***' in line:
            _current_street = 'river'; current_round_committed = 0; _hero_bet_this_street = False
        if hero_name not in line or ': ' not in line: continue
        # Posts (blinds/antes) — "posts small blind X" / "posts big blind X" / "posts the ante X"
        pm = re.match(rf'{re.escape(hero_name)}: posts (?:small blind|big blind|the ante) (\d[\d,]*(?:\.\d+)?)', line)
        if pm:
            amt = float(pm.group(1).replace(',', ''))
            hero_committed += amt
            current_round_committed += amt
            continue
        cm2 = re.match(rf'{re.escape(hero_name)}: calls (\d[\d,]*(?:\.\d+)?)', line)
        if cm2:
            amt = float(cm2.group(1).replace(',', ''))
            hero_committed += amt
            current_round_committed += amt
            # B253: if Hero already bet this street, this call is a call-of-raise
            if _hero_bet_this_street and _current_street != 'preflop':
                _street_nodes.setdefault(_current_street, []).append(
                    {'action': 'call_raise', 'amount': amt})
            continue
        bm = re.match(rf'{re.escape(hero_name)}: bets (\d[\d,]*(?:\.\d+)?)', line)
        if bm:
            amt = float(bm.group(1).replace(',', ''))
            hero_committed += amt
            current_round_committed += amt
            _hero_bet_this_street = True
            if _current_street != 'preflop':
                _street_nodes.setdefault(_current_street, []).append(
                    {'action': 'bet', 'amount': amt})
            continue
        rm = re.match(rf'{re.escape(hero_name)}: raises (\d[\d,]*(?:\.\d+)?) to (\d[\d,]*(?:\.\d+)?)', line)
        if rm:
            raise_to = float(rm.group(2).replace(',', ''))
            new_chips = raise_to - current_round_committed
            hero_committed += max(new_chips, 0)
            current_round_committed = raise_to
            _hero_bet_this_street = True
            continue

    hand['hero_committed_bb'] = hero_committed / bb
    # B253: populate hero_street_nodes — only for streets with bet-then-call
    # (split-verdict streets). Each entry: {'bet_bb': X, 'call_raise_bb': Y}.
    _split_streets = {}
    for _sn, _nodes in _street_nodes.items():
        _bets = [n for n in _nodes if n['action'] == 'bet']
        _calls = [n for n in _nodes if n['action'] == 'call_raise']
        if _bets and _calls:
            _split_streets[_sn] = {
                'bet_bb': round(sum(n['amount'] for n in _bets) / bb, 2),
                'call_raise_bb': round(sum(n['amount'] for n in _calls) / bb, 2),
            }
    hand['hero_street_nodes'] = _split_streets
    # v7.30 P0-5: detect chops. A chop happens when multiple players collect from the
    # same pot. Hero collected > 0 in a chop, but it's NOT a win — it's a tie.
    # Heuristic: count distinct "X collected" lines after SHOWDOWN; if >1 collector
    # AND amounts are within 10% of each other, it's a chopped pot.
    is_chop = False
    if collected > 0 and hand.get('went_to_sd'):
        summary_section = text.split('*** SHOWDOWN ***')[1] if '*** SHOWDOWN ***' in text else text
        # Match "<player> collected <amount>" lines anywhere after showdown (one per side pot/main pot)
        collect_lines = re.findall(r'(\S+) collected (\d[\d,]*(?:\.\d+)?)', summary_section)
        if len(collect_lines) >= 2:
            collectors = set(player for player, _ in collect_lines)
            if len(collectors) >= 2:
                # Check Hero is one of multiple collectors (not just side-pot scenario where Hero
                # won main and a different player won side — that's not a chop, that's a side-pot loss)
                hero_amounts = [float(amt.replace(',', '')) for p, amt in collect_lines if p == hero_name]
                other_amounts = [float(amt.replace(',', '')) for p, amt in collect_lines if p != hero_name]
                if hero_amounts and other_amounts:
                    # If Hero's collected total is roughly half (within 30%) of total pot collected,
                    # it's a chop — not Hero winning everything, not Hero losing everything
                    total_collected = sum(hero_amounts) + sum(other_amounts)
                    hero_share = sum(hero_amounts) / total_collected if total_collected > 0 else 0
                    if 0.30 <= hero_share <= 0.70:  # roughly even split
                        is_chop = True
    hand['is_chop'] = is_chop
    if collected > 0 and not is_chop:
        # Hero won the pot — net includes pot winnings + any returned excess
        hand['net_bb'] = (collected + returned - hero_committed) / bb
        hand['won'] = True
    elif is_chop:
        # Chop — net is collected (hero's share) + returned - committed
        hand['net_bb'] = (collected + returned - hero_committed) / bb
        hand['won'] = 'chop'
    elif returned > 0 and not hand['went_to_sd']:
        # Hero bet, everyone folded, excess returned. Hero won (just blinds/antes).
        hand['net_bb'] = (collected + returned - hero_committed) / bb
        hand['won'] = True
    elif hand['went_to_sd']:
        # Hero went to showdown and lost (collected=0). Returned excess still reduces loss.
        hand['net_bb'] = (returned - hero_committed) / bb
        hand['won'] = False
    else:
        # Hero folded — no collection, no return
        hand['net_bb'] = -hero_committed / bb
        hand['won'] = None if hero_committed <= (hand.get('sb_blind',0) + hand.get('ante',0)) else False

    # v8.12.4 (QA item 15): refine the river check buckets with showdown
    # information that wasn't available at action time:
    #   - a checked hand that WON the showdown demonstrably had showdown
    #     value (QJ-high vs a busted draw) -- not a give-up;
    #   - a pocket pair BELOW every board card that LOST carried no real
    #     showdown value -- file it as a give-up, not "showdown value".
    _ra_ref = hand.get('river_action')
    if _ra_ref in ('check_sdv', 'check_giveup') and hand.get('went_to_sd'):
        if _ra_ref == 'check_giveup' and hand.get('won') is True:
            hand['river_action'] = 'check_sdv'
        elif (_ra_ref == 'check_sdv' and hand.get('won') is False
              and len(hero_cards) == 2 and len(board) >= 5
              and hero_cards[0][0] == hero_cards[1][0]):
            _ord_ref = '23456789TJQKA'
            _pr_ref = _ord_ref.find(hero_cards[0][0])
            _b_lo_ref = min(_ord_ref.find(c[0]) for c in board[:5])
            if 0 <= _pr_ref < _b_lo_ref:
                hand['river_action'] = 'check_giveup'

    # D4: Pot ledger — parse Main pot / Side pot lines for multiway accounting
    pot_ledger = []
    _main_m = re.search(r'Main pot\s+([\d,]+)', text)
    _side_ms = re.findall(r'Side pot(?:\s*\d*)?\s+([\d,]+)', text)
    if _main_m or _side_ms:
        hand['has_side_pot'] = True
        # Parse who collected from each pot
        _summary = text[text.find('*** SUMMARY ***'):] if '*** SUMMARY ***' in text else ''
        _collectors = re.findall(r'(\S+) collected (\d[\d,]*(?:\.\d+)?)\s+from\s+(.*?)(?:\n|$)', _summary)
        if _main_m:
            _mp_size = float(_main_m.group(1).replace(',', ''))
            _mp_winners = [p for p, amt, src in _collectors if 'Main' in src or 'main' in src]
            if not _mp_winners:
                _mp_winners = [p for p, amt, src in _collectors][:1]
            pot_ledger.append({
                'pot_id': 'main',
                'size_bb': round(_mp_size / bb, 1),
                'winners': _mp_winners,
                'hero_eligible': True,
                'hero_won': hero_name in _mp_winners,
            })
        for _si, _sp_str in enumerate(_side_ms, 1):
            _sp_size = float(_sp_str.replace(',', ''))
            _sp_winners = [p for p, amt, src in _collectors
                          if f'Side' in src or f'side' in src]
            if not _sp_winners and _si == 1:
                _sp_winners = [p for p, amt, src in _collectors
                              if p not in (_mp_winners if _main_m else [])][:1]
            pot_ledger.append({
                'pot_id': f'side_{_si}',
                'size_bb': round(_sp_size / bb, 1),
                'winners': _sp_winners,
                'hero_eligible': True,
                'hero_won': hero_name in _sp_winners,
            })
    else:
        hand['has_side_pot'] = False
    hand['pot_ledger'] = pot_ledger

    hand['raw_text'] = text[:3000]

    # Batch 1 (R6): Disconnect / timeout detection. GG HH lines like
    # "PlayerName has timed out" or "PlayerName is disconnected".
    # Check each line — Hero's name must be ON the disconnect line itself.
    _dc_keywords = ('has timed out', 'is disconnected', 'is sitting out',
                    'timed out while being disconnected')
    _hero_dc = False
    _hero_lower = hero_name.lower()
    for _dc_line in text.lower().split('\n'):
        if _hero_lower in _dc_line and any(k in _dc_line for k in _dc_keywords):
            _hero_dc = True
            break
    hand['disconnected'] = _hero_dc

    # A2b-1: Build action ledger from already-parsed streets text.
    # Second pass over the same lines — avoids touching fragile preflop parser.
    action_ledger = []
    bb = hand.get('bb_blind', 1) or 1
    for _al_street in ('preflop', 'flop', 'turn', 'river'):
        # v8.17.1 Iter-1: track the per-street bet level + per-player round commit so
        # we can record `added_bb` = chips ACTUALLY put in by each action (exact for
        # raises: "raises X to Y" adds Y - prior-round-commit). This lets the decision
        # snapshot reconstruct decision-time remaining stacks without re-reading the
        # raw text. Blinds set the level; antes (dead money) do not.
        _al_level = 0.0           # current bet-to level this street (bb units)
        _al_round = {}            # player -> committed THIS street (bb units)
        for _al_line in streets.get(_al_street, '').split('\n'):
            _al_line = _al_line.strip()
            if not _al_line or ': ' not in _al_line:
                continue
            # Parse: "PlayerName: action amount[ to total][ and is all-in]"
            _al_m = re.match(r'(\S+):\s+(raises|bets|calls|checks|folds|posts \S+ \S+)\s*([\d,]*\.?\d*)?(?:\s+to\s+([\d,]*\.?\d*))?', _al_line)
            if not _al_m:
                continue
            _al_player = _al_m.group(1)
            _al_action = _al_m.group(2).split()[0]  # 'raises', 'bets', 'calls', 'checks', 'folds', 'posts'
            _al_amt_str = _al_m.group(3) or _al_m.group(4) or '0'
            _al_amt = float(_al_amt_str.replace(',', '')) if _al_amt_str else 0
            _al_amt_bb = round(_al_amt / bb, 2) if bb > 0 else 0
            _al_to = _al_m.group(4)
            _al_to_bb = (round(float(_al_to.replace(',', '')) / bb, 2)
                         if (_al_to and bb > 0) else None)
            _al_is_allin = 'all-in' in _al_line.lower()
            _al_pos = player_position.get(_al_player, '?') if 'player_position' in dir() else '?'
            # chips ADDED this action (bb units)
            _prev = _al_round.get(_al_player, 0.0)
            if _al_action == 'raises':
                _newlvl = _al_to_bb if _al_to_bb is not None else (_al_level + _al_amt_bb)
                _added = max(0.0, round(_newlvl - _prev, 2))
                _al_round[_al_player] = _newlvl
                _al_level = max(_al_level, _newlvl)
            elif _al_action == 'bets':
                _added = _al_amt_bb
                _al_round[_al_player] = _prev + _al_amt_bb
                _al_level = max(_al_level, _al_round[_al_player])
            elif _al_action == 'calls':
                _added = _al_amt_bb
                _al_round[_al_player] = _prev + _al_amt_bb
            elif _al_action == 'posts':
                _added = _al_amt_bb
                _al_round[_al_player] = _prev + _al_amt_bb
                if 'blind' in _al_line.lower():   # antes are dead money, not a bet level
                    _al_level = max(_al_level, _al_round[_al_player])
            else:                                  # checks / folds
                _added = 0.0
            # REV15 B: TYPED forced-post reason preserved from the RAW hand-history text at the
            # ledger boundary — the canonical source downstream code reads (never re-inferred by
            # amount/seat). "posts small blind" / "posts big blind" / "posts the ante".
            _post_type = None
            if _al_action == 'posts':
                _pl = _al_line.lower()
                if 'small blind' in _pl:
                    _post_type = 'small_blind'
                elif 'big blind' in _pl:
                    _post_type = 'big_blind'
                elif 'ante' in _pl:
                    _post_type = 'ante'
                else:
                    _post_type = 'unknown'
            _al_event = {
                'street': _al_street,
                'player': _al_player,
                'position': _al_pos,
                'action': _al_action,
                'amount_bb': _al_amt_bb,
                'added_bb': _added,
                'to_bb': _al_to_bb,
                'is_all_in': _al_is_allin,
            }
            if _post_type is not None:
                _al_event['post_type'] = _post_type
            action_ledger.append(_al_event)
    hand['action_ledger'] = action_ledger

    # v8.17.1 Iter-1: ONE canonical decision-time snapshot owns eff_stack_bb_at_decision
    # (and the full DecisionSnapshot). Computed here, after the ledger exists.
    try:
        from gem_decision_snapshot import build_decision_snapshot as _bld_snap
        _ds_snap = _bld_snap(hand)
        hand['decision_snapshot'] = _ds_snap
        _ds_eff = _ds_snap.get('effective_stack_vs_faced_aggressor')
        if _ds_eff is None:
            _ds_eff = _ds_snap.get('max_effective_stack_among_active_opponents')
        hand['eff_stack_bb_at_decision'] = (round(_ds_eff, 2) if _ds_eff is not None
                                            else hand.get('stack_bb'))
    except Exception:
        hand['eff_stack_bb_at_decision'] = hand.get('stack_bb')

    # Build full line label: Role_PotType_PosBucket_actions_outcome
    if hand['vpip'] and hand.get('line_actions', 'preflop_only') != 'preflop_only':
        outcome = 'won' if hand.get('won') else 'lost'
        sd = '_SD' if hand.get('went_to_sd') else ''
        hand['line'] = f"{hand.get('pot_type','SRP')}_{('PFR' if hand['pfr'] else 'Caller')}_{('IP' if hand.get('hero_ip') else 'OOP')}_{hand['line_actions']}{sd}_{outcome}"
    elif hand['vpip']:
        # Preflop only (won PF or folded to 3-bet)
        role = 'PFR' if hand['pfr'] else 'Caller'
        if hand.get('won'): hand['line'] = f"PF_{role}_won"
        elif hand.get('fold_to_3bet'): hand['line'] = f"PF_{role}_fold_to_3bet"
        elif hand.get('fold_to_4bet'): hand['line'] = f"PF_{role}_fold_to_4bet"
        elif hand.get('pf_allin'):
            outcome = 'won' if hand.get('won') else 'lost'
            hand['line'] = f"PF_{role}_allin_{outcome}"
        elif hand.get('pf_settled'):
            # v7.15.1: Hero called a villain all-in (villain(s) went all-in PF, Hero called, pot settled preflop)
            outcome = 'won' if hand.get('won') else 'lost'
            hand['line'] = f"PF_{role}_called_allin_{outcome}"
        else: hand['line'] = f"PF_{role}_fold"
    else:
        hand['line'] = 'fold_preflop'

    # === ACTION SUMMARY (v7.2) — brief human-readable string ===
    parts = []
    role_str = 'PFR' if hand['pfr'] else ('Caller' if hand['vpip'] else 'Fold')
    parts.append(role_str)
    if hand.get('pf_action') == 'fold' and not hand['vpip']:
        parts.append(f"folded {normalize_hand(hand.get('cards',[]))} FI at {hand['position']} {round(hand.get('stack_bb',0))}BB")
    elif hand.get('pf_allin'):
        # Hero was all-in preflop — no postflop decisions
        parts.append('PF ALL-IN')
        if hand.get('went_to_sd'):
            parts.append('SD ' + ('won' if hand.get('won') else 'lost'))
        elif hand.get('won'):
            parts.append('won')
    elif hand.get('pf_settled'):
        # v7.15.1: Hero called villain all-in preflop. Pot settled PF, board runs out.
        parts.append('called villain PF all-in')
        if hand.get('went_to_sd'):
            parts.append('SD ' + ('won' if hand.get('won') else 'lost'))
        elif hand.get('won'):
            parts.append('won')
    else:
        for sn in ['flop', 'turn', 'river']:
            sa = hand.get('hero_street_actions', {}).get(sn)
            if not sa: continue
            bets_this = [b for b in hand.get('hero_bets', []) if b[0] == sn]
            sz_str = f" {bets_this[0][1]:.0f}%" if bets_this else ''
            facing_this = [b for b in hand.get('facing_bets', []) if b[0] == sn]
            if sa == 'cbet': parts.append(f"cbet {sn}{sz_str}")
            elif sa == 'bet': parts.append(f"bet {sn}{sz_str}")
            elif sa == 'bet-call': parts.append(f"bet {sn}{sz_str} → call raise")
            elif sa == 'bet-fold': parts.append(f"bet {sn}{sz_str} → fold to raise")
            elif sa == 'bet-callAI': parts.append(f"bet {sn}{sz_str} → call all-in")
            elif sa in ('xc', 'call'): parts.append(f"call {sn}")
            elif sa == 'xr': parts.append(f"x/r {sn}")
            elif sa == 'xf': parts.append(f"x/f {sn}")
            elif sa == 'x': parts.append(f"check {sn}")
            elif sa == 'jam': parts.append(f"jam {sn}")
            elif sa == 'xr-ai': parts.append(f"x/r all-in {sn}")
            elif sa == 'xc-ai': parts.append(f"call all-in {sn}")
            elif sa == 'callAI': parts.append(f"call all-in {sn}")
            elif sa == 'fold': parts.append(f"fold {sn}")
            elif sa == 'raise': parts.append(f"raise {sn}{sz_str}")
        if hand.get('went_to_sd'):
            parts.append('SD ' + ('won' if hand.get('won') else 'lost'))
        elif hand.get('won') and hand['vpip']:
            parts.append('won')
    hand['action_summary'] = ', '.join(parts)

    # =========================================================================
    # v7.27 DERIVED FLAGS — facing-action defense + donk + barrel metrics
    # =========================================================================
    # All derived from existing fields. Defaults False/0 when not applicable.
    # Aggregator (gem_analyzer.py) computes per-population rates from these.
    hsa = hand.get('hero_street_actions') or {}
    hbets = hand.get('hero_bets') or []
    fbets = hand.get('facing_bets') or []
    is_pfr = bool(hand.get('pfr'))
    is_ip = bool(hand.get('hero_ip'))
    villain_bet_flop = bool(hand.get('villain_bet_flop_first'))

    # ---------- Facing villain's c-bet (Hero is caller, villain is PFR) ----------
    # Opportunity: villain bet flop AND Hero is non-PFR (Hero called preflop)
    hand['faced_villain_cbet_flop'] = (not is_pfr) and villain_bet_flop and bool(hand.get('vpip'))
    flop_action = hsa.get('flop')
    hand['fold_to_villain_cbet_flop'] = (
        hand['faced_villain_cbet_flop'] and flop_action in ('fold', 'xf')
    )
    hand['called_villain_cbet_flop'] = (
        hand['faced_villain_cbet_flop'] and flop_action in ('call', 'xc', 'xc-ai', 'callAI')
    )
    # Raise (non check-raise): IP Hero raises villain bet without checking
    hand['raised_villain_cbet_flop_ip'] = (
        hand['faced_villain_cbet_flop'] and is_ip and flop_action == 'raise'
    )
    # Check-raise (already tracked separately as hero_check_raised_flop)
    hand['xr_villain_cbet_flop'] = (
        hand['faced_villain_cbet_flop'] and flop_action in ('xr', 'xr-ai')
    )

    # ---------- Hero c-bet, villain raised (XR or IP raise) ----------
    # v8.12.4 (QA item 14, TM6058777821): the B253 composite codes
    # ('bet-call', 'bet-fold', 'bet-callAI') all START with a flop bet —
    # the PFR DID c-bet and then faced a raise. Matching only 'cbet'
    # mis-filed every cbet-then-raised hand as a MISSED c-bet.
    _CBET_FIRST_ACTIONS = ('cbet', 'bet-call', 'bet-fold', 'bet-callAI')
    hero_cbet_flop = is_pfr and flop_action in _CBET_FIRST_ACTIONS
    # v8.12.4: persist the flag — gem_analyzer reads h['hero_cbet_flop']
    # (bestplay frame picker + S5 drill counters) but it was never stored,
    # so those reads silently got None for every hand.
    hand['hero_cbet_flop'] = hero_cbet_flop
    hand['faced_xr_after_cbet'] = hero_cbet_flop and bool(hand.get('villain_raised_hero_cbet_flop'))
    # Hero's response — facing_bets logs Hero call/fold; otherwise check action codes
    flop_facing = [f for f in fbets if f and f[0] == 'flop']
    hand['folded_to_xr_after_cbet'] = (
        hand['faced_xr_after_cbet']
        and (any(f[2] == 'fold' for f in flop_facing) or flop_action == 'fold')
    )
    hand['called_xr_after_cbet'] = (
        hand['faced_xr_after_cbet']
        and any(f[2] == 'call' for f in flop_facing)
    )
    hand['reraised_xr_after_cbet'] = (
        hand['faced_xr_after_cbet']
        and flop_action in ('raise', 'jam')
        and not any(f[2] in ('call', 'fold') for f in flop_facing)
    )

    # ---------- Donk bets (Hero caller OOP leads) ----------
    hand['faced_donk_flop'] = is_pfr and bool(hand.get('villain_bet_flop_first'))
    # Hero PFR's response when villain (caller, OOP) donks. Same flop_action codes apply.
    hand['folded_to_donk_flop'] = hand['faced_donk_flop'] and flop_action in ('fold', 'xf')
    hand['called_donk_flop'] = hand['faced_donk_flop'] and flop_action in ('call', 'xc', 'callAI', 'xc-ai')
    hand['raised_donk_flop'] = hand['faced_donk_flop'] and flop_action in ('raise', 'jam', 'xr', 'xr-ai')

    # ---------- Triple barrel (Hero c-bet flop, bet turn, bet river) ----------
    turn_action = hsa.get('turn')
    river_action_code = hsa.get('river')
    # B253: bet-then-call/fold composites still count as "barreled" for the
    # barrel stat (Hero DID bet the street — that's the barrel).
    _BET_ACTS = ('bet', 'jam', 'bet-call', 'bet-fold', 'bet-callAI')
    hand['triple_barreled'] = (
        is_pfr
        and flop_action == 'cbet'
        and turn_action in _BET_ACTS
        and river_action_code in _BET_ACTS
    )
    hand['double_barreled'] = (
        is_pfr
        and flop_action == 'cbet'
        and turn_action in _BET_ACTS
    )

    # ---------- Faced double barrel (Hero called flop, villain bet turn) ----------
    hero_called_flop_as_caller = (not is_pfr) and flop_action in ('call', 'xc')
    turn_facing = [f for f in fbets if f and f[0] == 'turn']
    hand['faced_turn_barrel'] = hero_called_flop_as_caller and len(turn_facing) > 0
    hand['folded_to_turn_barrel'] = (
        hand['faced_turn_barrel']
        and (any(f[2] == 'fold' for f in turn_facing) or turn_action in ('fold', 'xf'))
    )
    hand['called_turn_barrel'] = (
        hand['faced_turn_barrel']
        and (any(f[2] == 'call' for f in turn_facing) or turn_action in ('call', 'xc'))
    )

    # ---------- Bet-Fold / Bet-Call (Hero bet, villain raised, Hero responded) ----------
    # Per street: Hero bet AND Hero faced villain raise on same street
    bet_streets = set(b[0] for b in hbets if b[2] in ('cbet', 'barrel', 'probe', 'bet'))
    for st_name in ('flop', 'turn', 'river'):
        bet_then_faced = st_name in bet_streets and any(f and f[0] == st_name for f in fbets)
        st_facing = [f for f in fbets if f and f[0] == st_name]
        hand[f'bet_then_faced_raise_{st_name}'] = bet_then_faced
        hand[f'bet_fold_{st_name}'] = bet_then_faced and any(f[2] == 'fold' for f in st_facing)
        hand[f'bet_call_{st_name}'] = bet_then_faced and any(f[2] == 'call' for f in st_facing)

    # ---------- Cold Call (Hero VPIP, faced raise, did not 3-bet, no villain jam) ----------
    hand['cold_called'] = (
        bool(hand.get('vpip'))
        and bool(hand.get('hero_faced_raise'))
        and not bool(hand.get('hero_3bet'))
        and not bool(hand.get('villain_jammed'))
        and bool(hand.get('first_in')) is False  # not first-in
    )

    # ---------- Cold Call 3-Bet (Hero called a 3-bet, was not the original opener) ----------
    # Heuristic: 3+ raises preflop, Hero VPIP'd but didn't open OR 3-bet OR 4-bet
    pf_raises = int(hand.get('pf_raise_count') or 0)
    hand['cold_called_3bet'] = (
        pf_raises >= 2
        and bool(hand.get('vpip'))
        and not bool(hand.get('first_in'))
        and not bool(hand.get('hero_3bet'))
        and (hand.get('pf_action') not in ('4bet+',))
    )

    # ---------- 4-bet / 5-bet split from pf_action='4bet+' ----------
    # 4-bet = pf_raise_count == 3 when Hero raised
    # 5-bet = pf_raise_count >= 4 when Hero raised
    # B-V10: hero_4bet_only was checking final pf_raises == 3, but if
    # villain re-jams AFTER Hero's 4-bet, final count becomes 4 and the
    # check failed. Fix: use _hero_raise_number (count AT Hero's raise).
    # Hero's raise was the Nth raise → 3 = 4-bet, 4+ = 5-bet.
    _hrn = locals().get('_hero_raise_number', 0)
    hand['hero_4bet_only'] = (hand.get('pf_action') == '4bet+' and _hrn == 3)
    hand['hero_5bet_plus'] = (hand.get('pf_action') == '4bet+' and _hrn >= 4)

    # ---------- Faced 5-bet (Hero 4-bet then faced re-raise → folded, called, jammed) ----------
    hand['faced_5bet'] = hand['hero_4bet_only'] and pf_raises >= 4

    # ---------- Faced steal in BB (Hero in BB, opener LP) ----------
    # BUG-2 (Ron review 2026-05-31): A spot only counts as a steal-defense
    # opportunity if Hero faces the steal raise DIRECTLY — no intervening
    # reraise. If pf_raise_count >= 2 and Hero didn't 3-bet, someone ELSE
    # 3-bet between the steal and Hero's decision → Hero is facing a "3bet+"
    # spot, not a steal-defense spot. Folding T5o into open+3bet is mandatory.
    _no_intervening_3bet = (
        (hand.get('pf_raise_count') or 0) <= 1  # just the steal open
        or hand.get('hero_3bet')                 # Hero 3-bet = defending via resteal
    )
    hand['faced_steal_bb'] = (
        hand.get('position') == 'BB'
        and hand.get('opener_position') in ('CO', 'BTN', 'SB', 'HJ')
        and not hand.get('villain_jammed')
        and _no_intervening_3bet
    )
    hand['fold_to_steal_bb'] = hand['faced_steal_bb'] and not bool(hand.get('vpip'))

    # ---------- Re-Steal (3-bet from blinds vs LP open) ----------
    hand['restole'] = (
        hand.get('position') in ('SB', 'BB')
        and hand.get('opener_position') in ('CO', 'BTN', 'SB', 'HJ')
        and bool(hand.get('hero_3bet'))
    )

    # ---------- Faced squeeze (Hero opened, faced 3-bet with caller in between) ----------
    # Heuristic: Hero opened, was 3-bet, AND there was a caller before the 3-bet.
    # The is_squeeze field captures Hero AS squeezer; we want Hero AS opener facing one.
    hand['faced_squeeze'] = (
        bool(hand.get('first_in'))
        and bool(hand.get('hero_faced_raise'))
        and pf_raises >= 2
        # caller-before-3bet inferred from pf_sequence having a 'calls' before the second 'raises'
        and bool(_had_caller_before_3bet(hand.get('pf_sequence', [])))
    )
    hand['folded_to_squeeze'] = hand['faced_squeeze'] and bool(hand.get('fold_to_3bet'))

    # ---------- Sub-15BB call jam ----------
    hand['lt15bb_call_jam'] = (
        bool(hand.get('villain_jammed'))
        and bool(hand.get('vpip'))
        and (hand.get('eff_stack_bb') or 0) <= 15
    )

    # =========================================================================
    # v7.28 DERIVED FLAGS — completes preflop matrices, c-bet by street/pot
    # type, check-raise response per street, showdown branches, river
    # efficiency primitives.
    # =========================================================================
    haf = hand.get('hero_action_flags') or {}

    # ---------- Preflop ratios + true PFR -----------
    pf_action = hand.get('pf_action') or ''
    # Forced action excluded: when in BB and walked OR limped pot with no raise.
    # Heuristic: True PFR opportunity = first_in OR (vpip AND faced raise AND not folded)
    hand['true_pfr_opportunity'] = bool(
        hand.get('first_in') or (hand.get('vpip') and hand.get('hero_faced_raise'))
    )
    hand['true_pfr_action'] = bool(hand.get('pfr')) and hand['true_pfr_opportunity']

    # ---------- 3-Bet IP/OOP split (uses hero_ip as preflop position proxy
    #            — valid for HU 3-bet pots; minor noise in MW)
    is_3bet = bool(hand.get('hero_3bet'))
    hand['hero_3bet_ip'] = is_3bet and is_ip
    hand['hero_3bet_oop'] = is_3bet and not is_ip
    hand['fold_to_3bet_ip'] = bool(hand.get('fold_to_3bet')) and is_ip
    hand['fold_to_3bet_oop'] = bool(hand.get('fold_to_3bet')) and not is_ip

    # ---------- Call 3-Bet / 4-Bet / 5-Bet (Hero as opener) -----------
    # Call 3-bet: Hero opened (first_in + pfr), faced raise (the 3-bet),
    # called (not folded, not 4-bet, not 5-bet)
    hero_opened = bool(hand.get('first_in')) and bool(hand.get('pfr'))
    hand['hero_called_3bet'] = (
        hero_opened
        and bool(hand.get('hero_faced_raise'))
        and bool(hand.get('vpip'))
        and not bool(hand.get('fold_to_3bet'))
        and pf_action != '4bet+'
        and not is_3bet  # if Hero re-3bet, that's 4bet not call-3bet
    )
    hand['hero_called_3bet_ip'] = hand['hero_called_3bet'] and is_ip
    hand['hero_called_3bet_oop'] = hand['hero_called_3bet'] and not is_ip

    # Call 4-bet: Hero 3-bet, faced 4-bet, called (didn't fold or 5-bet)
    hand['hero_called_4bet'] = (
        is_3bet
        and pf_raises >= 3
        and bool(hand.get('vpip'))
        and not bool(hand.get('fold_to_4bet'))
        and pf_action != '4bet+'
    )

    # Call 5-bet: Hero 4-bet, faced 5-bet, called
    hand['hero_called_5bet'] = (
        bool(hand.get('hero_4bet_only'))
        and pf_raises >= 4
        and bool(hand.get('vpip'))
        # If Hero went all-in 5-bet+ that's hero_5bet_plus, separate
    )

    # ---------- Squeeze response (Hero as opener facing squeeze) -----------
    hand['called_squeeze'] = (
        bool(hand.get('faced_squeeze'))
        and bool(hand.get('vpip'))
        and not bool(hand.get('fold_to_3bet'))
        and pf_action != '4bet+'
    )
    hand['raised_squeeze'] = (
        bool(hand.get('faced_squeeze'))
        and pf_action == '4bet+'
    )

    # ---------- Steal & blind combat splits -----------
    opener_pos = hand.get('opener_position') or ''
    hand['called_steal_bb'] = (
        bool(hand.get('faced_steal_bb'))
        and bool(hand.get('vpip'))
        and not is_3bet
    )
    hand['fold_bb_to_sb_steal'] = (
        hand.get('position') == 'BB'
        and opener_pos == 'SB'
        and not bool(hand.get('vpip'))
        and not bool(hand.get('villain_jammed'))
    )
    hand['fold_sb_to_btn_steal'] = (
        hand.get('position') == 'SB'
        and opener_pos == 'BTN'
        and not bool(hand.get('vpip'))
        and not bool(hand.get('villain_jammed'))
    )
    hand['sb_defended_vs_steal'] = (
        hand.get('position') == 'SB'
        and opener_pos in ('CO', 'BTN', 'HJ')
        and bool(hand.get('vpip'))
        and not bool(hand.get('villain_jammed'))
    )
    hand['bb_3bet_vs_btn'] = (
        hand.get('position') == 'BB'
        and opener_pos == 'BTN'
        and is_3bet
    )
    hand['bb_3bet_vs_sb'] = (
        hand.get('position') == 'BB'
        and opener_pos == 'SB'
        and is_3bet
    )
    # Hero stole and faced a 3-bet from BB (Hero opened CO/BTN/SB, BB 3-bet)
    hand['hero_stole_faced_bb_3bet'] = (
        hand.get('position') in ('CO', 'BTN', 'SB')
        and bool(hand.get('first_in'))
        and bool(hand.get('hero_faced_raise'))
        and pf_raises >= 2
    )
    hand['hero_folded_to_bb_3bet'] = (
        hand['hero_stole_faced_bb_3bet']
        and bool(hand.get('fold_to_3bet'))
    )

    # ---------- All-in preflop rate primitive -----------
    hand['pf_allin_flag'] = bool(hand.get('pf_allin'))

    # ---------- C-Bet by street (Hero as PFR) — turn / river response splits ----------
    # (We already have flop responses in v7.27 — extend to turn/river.)
    facing_turn = [f for f in fbets if f and f[0] == 'turn']
    facing_river = [f for f in fbets if f and f[0] == 'river']
    villain_bet_turn = len(facing_turn) > 0  # Hero acted facing villain bet on turn
    villain_bet_river = len(facing_river) > 0

    # As caller, faced villain c-bet/barrel on turn / river:
    hand['faced_villain_bet_turn'] = (not is_pfr) and bool(hand.get('vpip')) and villain_bet_turn
    hand['fold_to_villain_bet_turn'] = (
        hand['faced_villain_bet_turn']
        and (turn_action in ('fold', 'xf') or any(f[2] == 'fold' for f in facing_turn))
    )
    hand['called_villain_bet_turn'] = (
        hand['faced_villain_bet_turn']
        and (turn_action in ('call', 'xc', 'callAI', 'xc-ai')
             or any(f[2] == 'call' for f in facing_turn))
    )
    hand['raised_villain_bet_turn'] = (
        hand['faced_villain_bet_turn']
        and turn_action in ('raise', 'jam', 'xr', 'xr-ai')
    )

    hand['faced_villain_bet_river'] = (not is_pfr) and bool(hand.get('vpip')) and villain_bet_river
    hand['fold_to_villain_bet_river'] = (
        hand['faced_villain_bet_river']
        and (river_action_code in ('fold', 'xf') or any(f[2] == 'fold' for f in facing_river))
    )
    hand['called_villain_bet_river'] = (
        hand['faced_villain_bet_river']
        and (river_action_code in ('call', 'xc', 'callAI', 'xc-ai')
             or any(f[2] == 'call' for f in facing_river))
    )
    hand['raised_villain_bet_river'] = (
        hand['faced_villain_bet_river']
        and river_action_code in ('raise', 'jam', 'xr', 'xr-ai')
    )

    # ---------- C-Bet by pot type (SRP / 3BP / 4BP) ----------
    pot_type_h = hand.get('pot_type') or 'SRP'
    # v8.12.4 (QA item 14): include the B253 composite codes — a bet that
    # then faced a raise is still a c-bet (see _CBET_FIRST_ACTIONS above).
    is_cbet_flop = is_pfr and flop_action in _CBET_FIRST_ACTIONS
    hand['cbet_flop_3bp'] = is_cbet_flop and pot_type_h == '3BP'
    hand['cbet_flop_4bp'] = is_cbet_flop and pot_type_h == '4BP'
    hand['cbet_flop_srp'] = is_cbet_flop and pot_type_h == 'SRP'
    # As caller in 3BP / 4BP facing villain c-bet
    hand['faced_villain_cbet_flop_3bp'] = (
        hand.get('faced_villain_cbet_flop')
        and pot_type_h == '3BP'
    )
    hand['faced_villain_cbet_flop_4bp'] = (
        hand.get('faced_villain_cbet_flop')
        and pot_type_h == '4BP'
    )
    hand['fold_to_cbet_flop_3bp'] = (
        hand['faced_villain_cbet_flop_3bp']
        and bool(hand.get('fold_to_villain_cbet_flop'))
    )
    hand['fold_to_cbet_flop_4bp'] = (
        hand['faced_villain_cbet_flop_4bp']
        and bool(hand.get('fold_to_villain_cbet_flop'))
    )

    # ---------- Multiway c-bet (3+ players to flop) ----------
    multiway_flop = (hand.get('players_at_flop') or 0) >= 3
    hand['multiway_flop'] = multiway_flop
    hand['cbet_flop_mw'] = is_cbet_flop and multiway_flop
    hand['faced_mw_cbet_flop'] = (
        bool(hand.get('faced_villain_cbet_flop')) and multiway_flop
    )
    hand['fold_to_mw_cbet'] = (
        hand['faced_mw_cbet_flop']
        and bool(hand.get('fold_to_villain_cbet_flop'))
    )

    # ---------- Delayed C-Bet TURN (Hero PFR, checked flop, bet turn) ----------
    hand['delayed_cbet_turn'] = (
        is_pfr
        and flop_action in ('x', 'xc', 'xf')  # Hero didn't bet flop
        and turn_action in _BET_ACTS
    )

    # ---------- Probe rates (NOT just missed — actual probe attempts) ----------
    # Probe = Hero non-PFR, IP, HU, PFR checked the previous street, Hero bets.
    # Per-street: turn probe (after villain checked flop) / river probe
    hand['probe_turn'] = (
        (not is_pfr) and bool(hand.get('vpip')) and is_ip
        and (hand.get('players_at_flop') or 0) == 2
        and flop_action in ('x', None)  # both checked through flop
        and not bool(hand.get('villain_bet_flop_first'))
        and turn_action in _BET_ACTS
    )

    # ---------- Check-Raise per street + responses (general, not just after cbet) ----------
    for st in ('flop', 'turn', 'river'):
        sa = hsa.get(st)
        st_facing = [f for f in fbets if f and f[0] == st]
        st_flags = haf.get(st) or {}
        v_xr = bool(hand.get(f'villain_xr_{st}'))
        # Hero's check-raise count is already tracked via 'xr'/'xr-ai' codes
        hand[f'hero_check_raise_{st}'] = sa in ('xr', 'xr-ai')
        # When Hero faced a villain check-raise (Hero bet into a check, villain raised)
        hand[f'faced_xr_{st}'] = v_xr
        # Hero's response to that XR — fold / call / raise (3-bet flop)
        hand[f'fold_to_xr_{st}'] = v_xr and (
            any(f[2] == 'fold' for f in st_facing) or sa == 'fold'
        )
        hand[f'call_xr_{st}'] = v_xr and any(f[2] == 'call' for f in st_facing)
        # Re-raise = Hero bet AND Hero raised on same street (only possible if villain raised in between)
        hand[f'reraise_xr_{st}'] = (
            v_xr
            and st_flags.get('bet')
            and st_flags.get('raise')
        )

    # ---------- Bet-Raise per street (Hero bet, faced raise, re-raised) ----------
    # Distinct from bet_fold/bet_call (already in v7.27). Same street, Hero
    # bet then raised = re-raised after villain's raise.
    for st in ('flop', 'turn', 'river'):
        st_flags = haf.get(st) or {}
        hand[f'bet_raise_{st}'] = bool(st_flags.get('bet')) and bool(st_flags.get('raise'))

    # ---------- Showdown branch metrics ----------
    went_sd = bool(hand.get('went_to_sd'))
    won_h = bool(hand.get('won'))
    hand['cbet_flop_then_sd'] = is_cbet_flop and went_sd
    hand['called_flop_cbet_then_sd'] = (
        bool(hand.get('called_villain_cbet_flop')) and went_sd
    )
    hand['cbet_turn_then_sd'] = (
        is_pfr and turn_action in _BET_ACTS and went_sd
    )
    # WSD branches — Hero won at showdown after specific river action
    hand['called_river_then_won_sd'] = (
        river_action_code in ('call', 'xc', 'callAI', 'xc-ai')
        and went_sd and won_h
    )
    hand['called_river'] = (
        river_action_code in ('call', 'xc', 'callAI', 'xc-ai')
    )
    hand['raised_river'] = (
        river_action_code in ('raise', 'jam', 'xr', 'xr-ai')
    )
    hand['raised_river_then_won_sd'] = hand['raised_river'] and went_sd and won_h
    hand['hero_bet_river'] = river_action_code in _BET_ACTS

    # ---------- River efficiency primitives (net_bb deltas; analyzer averages) ----------
    # Just tag the action class; analyzer aggregates net_bb means per class.
    if river_action_code in ('call', 'xc', 'callAI', 'xc-ai'):
        hand['river_action_class'] = 'call'
    elif river_action_code in _BET_ACTS:
        hand['river_action_class'] = 'bet'
    elif river_action_code in ('raise', 'xr', 'xr-ai'):
        hand['river_action_class'] = 'raise'
    else:
        hand['river_action_class'] = ''

    # BUG FIX: null out board-derived fields on hands where Hero never PLAYED postflop.
    # The parser parses the community cards from the HH even when Hero isn't in the hand
    # (other players went to showdown). This creates "phantom boards" on fold-preflop hands
    # with spr/hand_strength/draw_type populated as if Hero saw the flop.
    #
    # v8.21 (handover #1, canonical promotion of the v8.20-LOCAL-DIAG): a BB CHECK
    # (vpip=0, pf_action='check') still SEES the flop and can play the whole hand. Wiping
    # its board mislabels a real postflop hand as 'folded_preflop' and, worse, feeds an EMPTY
    # board into the hand's turn/river decision records -> the sealed analyst packet fails
    # closed ('board length 0 != turn requires 4') and the whole analyst pass is withheld.
    # Only treat Hero as "not in the pot" when Hero genuinely did NOT play postflop: folded
    # preflop, or checked/walked without committing beyond the blind. went_to_sd, or more than
    # the ~1.5bb blind committed, proves Hero played the board for real -> preserve it.
    _hero_played_postflop = bool(hand.get('went_to_sd')) or (
        float(hand.get('hero_committed_bb', 0) or 0) > 1.5)
    if (not hand.get('vpip') and hand.get('pf_action') in ('fold', 'check')
            and not _hero_played_postflop):
        # Hero didn't voluntarily put money in / never played the flop — board is irrelevant
        hand['board'] = []
        hand['board_texture'] = 'none'
        hand['board_archetype'] = ''
        hand['spr'] = 0
        hand['hand_strength'] = 'folded_preflop'
        hand['draw_type'] = 'none'
        hand['players_at_flop'] = 0

    return hand


def _had_caller_before_3bet(pf_seq):
    """Helper for faced_squeeze: was there a 'calls' before a 'raises' in the second raise position?"""
    if not pf_seq or not isinstance(pf_seq, list):
        return False
    saw_open = False
    saw_call_after_open = False
    raise_count = 0
    for entry in pf_seq:
        if not isinstance(entry, str):
            continue
        e = entry.lower()
        if 'raises' in e or 'all-in' in e:
            raise_count += 1
            if not saw_open:
                saw_open = True
            elif saw_call_after_open and raise_count >= 2:
                return True
        elif 'calls' in e and saw_open:
            saw_call_after_open = True
    return False


