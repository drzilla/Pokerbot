"""
gem_pot_odds.py — Pot-odds & equity computation for all-in call decisions
==========================================================================
Ron 2026-05-26. Every all-in call the analyst writes a verdict on now carries
the arithmetic the Analyst Writing Checklist §3b mandates: the call price ->
required equity, and Hero's actual equity — so an argument states the numbers
instead of asserting "near-dead" / "drawing thin" without them.

BUG-5 fix (v7.99, Ron 2026-05-30): equity is now RANGE-BASED for preflop
all-ins, not vs the single shown villain hand. The shown-hand equity is kept
as `realized_equity_vs_shown` (clearly labelled result-derived) and is NEVER
fed into verdict_hint or ev_call_bb. This eliminates the result-leak where
every won hand showed ~100% equity and every lost hand ~0%.

BUG-6 fix (v7.99, Ron 2026-05-30): for multi-street call-downs, pot odds are
computed at EACH decision street, not just the all-in street. The earliest
street where the call was questionable is surfaced as `root_decision_street`.

BUG-7 fix (v7.99, Ron 2026-05-30): multiway pots with all-in short stacks
are detected and flagged. When Hero folds to a side-pot bet while having
equity in the main pot, a `multiway_overfold` flag is emitted.

What it computes, per qualifying hand:
  - call_bb, pot_bb            — reconstructed from the raw HH
  - required_eq_pct            — to_call / total_pot   (exact)
  - required_eq_bounty_pct     — required minus the gem_bounty discount, when
                                 a covered villain makes the bounty live
  - hero_equity_pct            — vs villain's DECISION-TIME RANGE (preflop:
                                 MC vs jam-range bucket; postflop: unavailable
                                 in v1 — clearly flagged)
  - realized_equity_vs_shown   — RESULT-DERIVED exact equity vs the shown hand;
                                 kept for integrity checks, never fed to verdict
  - ev_call_bb                 — chip-EV of the call vs folding (range-based)
  - verdict_hint               — +EV / -EV / borderline, gated on range equity;
                                 when range unavailable: "do not grade on result"
  - per_street_calls            — BUG-6: pot odds at each street Hero called
  - root_decision_street       — BUG-6: earliest street where call is questionable
  - multiway_flag               — BUG-7: set when main/side pot split detected
  - integrity_flag             — set if the phevaluator showdown winner
                                 disagrees with the recorded result

SCOPE (v2): Hero-CALLS-all-in decisions, any street. Hero-as-jammer EV is
gem_pko's domain; non-all-in calls need implied odds and are out of scope
(clearly flagged, not silently computed).
"""
import re
import random
from itertools import combinations

try:
    from phevaluator import evaluate_cards
    _PHEV_OK = True
except Exception:
    _PHEV_OK = False

try:
    import gem_bounty
    _BOUNTY_OK = True
except Exception:
    _BOUNTY_OK = False

# Range-based equity infrastructure (BUG-5)
try:
    from gem_solver import expand_range, remove_conflicts, preflop_equity_vs_range
    _RANGE_OK = True
except Exception:
    _RANGE_OK = False

_RANKS = '23456789TJQKA'
_SUITS = 'cdhs'
_FULL_DECK = [r + s for r in _RANKS for s in _SUITS]

# Monte-Carlo sample size for the preflop case (board unknown -> exact
# enumeration is 1.7M run-outs; a 20k sample is within ~0.3pp and fast).
_MC_SAMPLES = 20000


# ---------------------------------------------------------------------------
# Jam-range model — villain's preflop jamming range by effective stack depth.
# Mirrored from gem_pko.py to avoid circular imports. These are the same
# depth-bucketed approximations used for CVJ evaluation.
# ---------------------------------------------------------------------------
_JAM_RANGE_BUCKETS = [
    (12.0, "22+ A2s+ K2s+ Q5s+ J7s+ T7s+ 97s+ 86s+ 76s 65s "
           "A2o+ K7o+ Q9o+ J9o+ T9o"),                                # ~very wide
    (22.0, "22+ A2s+ K6s+ Q9s+ J9s+ T9s 98s A5o+ K9o+ QTo+ JTo"),      # ~38%
    (35.0, "22+ A8s+ A5s K9s+ QTs+ JTs A9o+ KJo+ QJo"),                # ~22%
    (999.0, "55+ A9s+ KTs+ QJs AJo+ KQo"),                             # ~13%
]

_RANKORD = '23456789TJQKA'


def _bucket_spec(buckets, eff_bb):
    """Return the range spec string for the matching depth bucket."""
    for thresh, spec in buckets:
        if eff_bb <= thresh:
            return spec
    return buckets[-1][1]


def _expand_plus(tok):
    """Expand one range token to explicit hand descriptions."""
    tok = tok.strip()
    if not tok:
        return []
    plus = tok.endswith('+')
    base = tok[:-1] if plus else tok
    if len(base) == 4:
        return [base]
    if len(base) == 2 and base[0] == base[1]:
        if plus:
            i = _RANKORD.index(base[0])
            return [r + r for r in _RANKORD[i:]]
        return [base]
    if len(base) == 3:
        r1, r2, k = base[0], base[1], base[2]
        if plus:
            i1, i2 = _RANKORD.index(r1), _RANKORD.index(r2)
            return [r1 + _RANKORD[j] + k for j in range(i2, i1)]
        return [base]
    return [base]


def _jam_range_combos(eff_bb, dead_cards):
    """Build villain jam range combos for a given effective stack depth."""
    if not _RANGE_OK:
        return []
    spec_str = _bucket_spec(_JAM_RANGE_BUCKETS, eff_bb)
    descs = []
    for tok in spec_str.split():
        descs.extend(_expand_plus(tok))
    combos = expand_range([{'desc': d} for d in descs])
    return remove_conflicts(combos, dead_cards)


# ---------------------------------------------------------------------------
# Equity — exact enumeration (board >= 3 cards) / Monte-Carlo (preflop)
# ---------------------------------------------------------------------------
def enumerate_equity(hero_cards, villain_hands, board):
    """Hero's equity (%) at the current street against one or more KNOWN
    villain hands.

    hero_cards    : ['Ah','6d']
    villain_hands : [['4h','8h'], ...]  one or more 2-card villain hands
    board         : 0-5 community cards already out

    Returns a float 0-100 (win share + half of each tie), or None if the
    inputs are malformed. board>=3 -> exact enumeration; board<3 -> MC sample.
    """
    if not _PHEV_OK:
        return None
    hero = list(hero_cards or [])
    villains = [list(v) for v in (villain_hands or []) if v]
    board = list(board or [])
    if len(hero) != 2 or not villains:
        return None
    known = hero + board + [c for v in villains for c in v]
    if len(known) != len(set(known)):
        return None                       # duplicate card -> bad data
    deck = [c for c in _FULL_DECK if c not in known]
    need = 5 - len(board)
    if need < 0:
        return None

    def _score_runout(full_board):
        hero_rank = evaluate_cards(*hero, *full_board)
        vill_ranks = [evaluate_cards(*v, *full_board) for v in villains]
        best_v = min(vill_ranks)
        if hero_rank < best_v:
            return 1.0                    # Hero wins outright
        if hero_rank > best_v:
            return 0.0                    # Hero loses
        # tie for best — split among everyone tied at the top
        n_tied = 1 + sum(1 for r in vill_ranks if r == hero_rank)
        return 1.0 / n_tied

    total = 0.0
    n = 0
    if need == 0:
        total, n = _score_runout(board), 1
    elif need <= 2 and len(deck) >= need:
        # exact: flop (2 to come) is C(45,2)=990; turn (1) is 44 — both cheap
        for combo in combinations(deck, need):
            total += _score_runout(board + list(combo))
            n += 1
    else:
        # preflop (need 3-5) — Monte-Carlo sample
        rng = random.Random(0xC0FFEE)     # fixed seed -> reproducible
        for _ in range(_MC_SAMPLES):
            total += _score_runout(board + rng.sample(deck, need))
            n += 1
    return round(100.0 * total / n, 1) if n else None


# ---------------------------------------------------------------------------
# BUG-5: Range-based equity (decision-time faithful, not result-leaked)
# ---------------------------------------------------------------------------
def compute_range_equity(hero_cards, board_at_decision, eff_stack_bb, street):
    """Compute Hero's equity vs villain's estimated decision-time range.

    Returns (equity_pct, mode, note) where:
      - equity_pct: float 0-100, or None if unavailable
      - mode: 'range_mc' | 'unavailable'
      - note: human-readable explanation
    """
    if not _RANGE_OK or not _PHEV_OK:
        return None, 'unavailable', 'range infrastructure not available'

    if street == 'preflop' and len(board_at_decision) == 0:
        # Preflop all-in: use villain's jam range by effective stack
        dead = set(hero_cards)
        combos = _jam_range_combos(eff_stack_bb, dead)
        if not combos:
            return None, 'unavailable', 'empty jam range after conflict removal'
        eq, n = preflop_equity_vs_range(hero_cards, combos)
        if eq is None:
            return None, 'unavailable', 'MC equity computation failed'
        return eq, 'range_mc', (
            f"MC vs {len(combos)}-combo jam range "
            f"(eff {eff_stack_bb:.0f}BB bucket), n={n}")

    # Postflop range estimation is not yet supported (v1 limitation).
    # The correct fix requires constructing a villain range from:
    # position, action sequence, board texture, and stack depth.
    # gem_ranges.construct_villain_river_range() can do this for river
    # scenarios but needs position data not always available from raw HH.
    return None, 'unavailable', (
        f'postflop ({street}) range estimation not yet supported — '
        f'grade manually, do not rely on shown-hand equity')


# ---------------------------------------------------------------------------
# Raw-HH reconstruction — Hero's all-in call, any street
# ---------------------------------------------------------------------------
def reconstruct_allin_call(raw_hh, hero_name='Hero'):
    """Parse a raw HH; return a context dict when Hero made an all-in CALL,
    else None.

    Once the money is all in, GG's "Total pot" line is final and the uncalled
    remainder is already excluded — so pot_before_call = total_pot - to_call
    and required_equity = to_call / total_pot hold on EVERY street.

    Returns: bb, street, to_call_bb, total_pot_bb, pot_before_call_bb,
             required_eq_pct, hero_cards, villain_hands, board_at_decision,
             board_final, hero_covers_all, hero_won, n_players_at_showdown
    """
    if not raw_hh or not _PHEV_OK:
        return None
    raw = raw_hh.replace(',', '')

    bb_m = re.search(r'Level\d+\((\d+)/(\d+)', raw)
    if not bb_m:
        return None
    bb = float(bb_m.group(2))
    if bb <= 0:
        return None

    # Hero's all-in call.
    call_m = re.search(rf'{re.escape(hero_name)}:\s+calls\s+(\d+)\s+and is all-in', raw)
    if not call_m:
        return None
    to_call = float(call_m.group(1))
    if to_call <= 0:
        return None
    call_pos = call_m.start()

    # Street of the call: count board markers appearing before it.
    street = 'preflop'
    for marker, label in (('*** FLOP ***', 'flop'),
                          ('*** TURN ***', 'turn'),
                          ('*** RIVER ***', 'river')):
        idx = raw.find(marker)
        if 0 <= idx < call_pos:
            street = label

    total_pot_m = re.search(r'Total pot\s+(\d+)', raw)
    if not total_pot_m:
        return None
    total_pot = float(total_pot_m.group(1))
    pot_before = total_pot - to_call
    if pot_before <= 0:
        return None

    # Hero cards.
    hc = re.search(rf'Dealt to {re.escape(hero_name)} \[(\w\w) (\w\w)\]', raw)
    if not hc:
        return None
    hero_cards = [hc.group(1), hc.group(2)]

    # Final board.
    board_final = []
    bm = re.search(r'Board \[([2-9TJQKA cdhs]+)\]', raw)
    if bm:
        board_final = bm.group(1).split()

    # Board visible at the decision street.
    street_cards = {'preflop': 0, 'flop': 3, 'turn': 4, 'river': 5}
    board_at_decision = board_final[:street_cards.get(street, 0)]

    # Villain hands shown at showdown (everyone except Hero).
    # v8.12.8 QA3 (66662469): GG sometimes reveals a FOLDED player's cards
    # ("6c0e3680: shows [Kh 8d]" after folding the flop) — counting them
    # made the equity "9.5% (multiway — 3 players)" against a hand that was
    # never live at the all-in. Exclude anyone the summary marks folded.
    _folded_players = set(re.findall(
        r'Seat \d+:\s+(\S+?)(?:\s+\([^)]+\))?\s+folded', raw))
    villain_hands = []
    for m in re.finditer(r'(\S+):\s+show(?:s|ed)\s+\[(\w\w) (\w\w)\]', raw):
        if m.group(1) != hero_name and m.group(1) not in _folded_players:
            villain_hands.append([m.group(2), m.group(3)])

    # BUG-7: count players at showdown for multiway detection
    n_players_sd = 1 + len(villain_hands)  # Hero + shown villains

    # Seat stacks -> does Hero cover the whole field he is all-in against?
    stacks = {}
    for m in re.finditer(r'Seat \d+:\s+(\S+)\s+\((\d+) in chips\)', raw):
        stacks[m.group(1)] = float(m.group(2))
    hero_stack = stacks.get(hero_name, 0.0)
    others = [v for k, v in stacks.items() if k != hero_name]
    hero_covers_all = bool(others) and all(hero_stack >= o for o in others)

    # Recorded result — Hero collected from the pot?
    hero_won = bool(re.search(
        rf'{re.escape(hero_name)} (?:collected|wins)', raw)) or bool(
        re.search(rf'Seat \d+: {re.escape(hero_name)}[^\n]*\bwon\b', raw))

    return {
        'bb': bb,
        'street': street,
        'to_call_bb': round(to_call / bb, 1),
        'total_pot_bb': round(total_pot / bb, 1),
        'pot_before_call_bb': round(pot_before / bb, 1),
        'required_eq_pct': round(to_call / total_pot * 100.0, 1),
        'hero_cards': hero_cards,
        'villain_hands': villain_hands,
        'board_at_decision': board_at_decision,
        'board_final': board_final,
        'hero_covers_all': hero_covers_all,
        'hero_won': hero_won,
        'n_players_at_showdown': n_players_sd,
    }


# ---------------------------------------------------------------------------
# BUG-6: Per-street call detection — find all streets where Hero called
# ---------------------------------------------------------------------------
def _parse_per_street_calls(raw_hh, bb, hero_name='Hero'):
    """Parse the raw HH for Hero's non-all-in calls on each street.
    Returns a list of dicts: [{street, call_chips, pot_before_call_chips}, ...]
    for each street where Hero made a call (non-all-in)."""
    if not raw_hh:
        return []
    raw = raw_hh.replace(',', '')

    # Split by street markers
    street_markers = [
        ('*** HOLE CARDS ***', 'preflop'),
        ('*** FLOP ***', 'flop'),
        ('*** TURN ***', 'turn'),
        ('*** RIVER ***', 'river'),
    ]
    streets_text = {}
    lines = raw.split('\n')
    current_street = None
    current_lines = []
    for line in lines:
        for marker, sname in street_markers:
            if marker in line:
                if current_street:
                    streets_text[current_street] = '\n'.join(current_lines)
                current_street = sname
                current_lines = []
                break
        else:
            if current_street:
                current_lines.append(line)
    if current_street:
        streets_text[current_street] = '\n'.join(current_lines)

    # Parse blinds/antes for initial pot
    blind_pot = 0.0
    for m in re.finditer(r'\S+:\s+posts (?:small blind|big blind|the ante)\s+(\d+)', raw):
        blind_pot += float(m.group(1))

    # Walk each street and track pot + hero calls
    results = []
    running_pot = blind_pot
    hero_esc = re.escape(hero_name)

    for sname in ('preflop', 'flop', 'turn', 'river'):
        stext = streets_text.get(sname, '')
        if not stext:
            continue
        # Track all actions on this street to compute pot at hero's decision
        street_pot_additions = 0.0
        hero_called_this_street = False
        hero_call_amount = 0.0
        pot_at_hero_call = 0.0

        for line in stext.split('\n'):
            line = line.strip()
            # Skip Hero's own actions for pot tracking UNTIL we find the call
            # (pot_before_call = pot BEFORE hero's action)

            # Check for Hero's non-all-in call
            hc = re.match(rf'{hero_esc}:\s+calls\s+(\d+)(?!\s+and is all-in)', line)
            if hc:
                hero_call_amount = float(hc.group(1))
                pot_at_hero_call = running_pot + street_pot_additions
                hero_called_this_street = True
                street_pot_additions += hero_call_amount
                continue

            # Track all chip contributions (bets, calls, raises) for pot
            amt_m = re.match(r'\S+:\s+(?:bets|calls|raises.*to)\s+(\d+)', line)
            if amt_m:
                street_pot_additions += float(amt_m.group(1))

        if hero_called_this_street and hero_call_amount > 0:
            total_at_call = pot_at_hero_call + hero_call_amount
            results.append({
                'street': sname,
                'call_bb': round(hero_call_amount / bb, 1),
                'pot_before_call_bb': round(pot_at_hero_call / bb, 1),
                'total_pot_bb': round(total_at_call / bb, 1),
                'required_eq_pct': round(hero_call_amount / total_at_call * 100, 1)
                    if total_at_call > 0 else 0.0,
            })
        running_pot += street_pot_additions

    return results


def compute_nonallin_pot_odds(hand, raw_hh, hero_name='Hero'):
    """v8.12.8 (handover Issue 1): lightweight pot-odds block for hands where
    Hero called bets WITHOUT going all-in. reconstruct_allin_call returns
    None for these, so deep multi-street (over)bet calldowns — exactly the
    spots a human eyeballs wrong — reached the analyst worksheet with
    _pot_odds=None and the verdict was guessed (TM6066411207: a 117%-pot
    overbet call needing 35.1% was cleared as "roughly pot-sized").
    Reuses _parse_per_street_calls, which already computes the right
    numbers; needs NO equity engine (pure pot arithmetic)."""
    if not raw_hh:
        return None
    raw = raw_hh.replace(',', '')
    bb_m = re.search(r'Level\d+\((\d+)/(\d+)', raw)
    if not bb_m:
        return None
    bb = float(bb_m.group(2))
    if bb <= 0:
        return None
    # All-in calls belong to compute_hand_pot_odds (full equity treatment).
    if re.search(rf'{re.escape(hero_name)}:\s+calls\s+(\d+)\s+and is all-in',
                 raw):
        return None
    try:
        per_street = _parse_per_street_calls(raw_hh, bb, hero_name)
    except Exception:
        return None
    if not per_street:
        return None

    summary = []
    for ps in per_street:
        _pot_before = ps.get('pot_before_call_bb') or 0
        _call = ps.get('call_bb') or 0
        # pot_before_call INCLUDES the bet Hero faces; the sizing fraction
        # is bet / pot-before-the-bet (call ≈ the bet when it closes a
        # single bet — the dominant calldown shape).
        _pre_bet = _pot_before - _call
        ps['bet_pct_of_pot'] = (round(_call / _pre_bet * 100.0)
                                if _pre_bet > 0 else None)
        # The single most important signal: an overbet pushes required
        # equity past where draws continue (always > 33.3%). Preflop is
        # excluded — raise-facing calls are normally >100% of the tiny
        # blind pot; pot-fraction framing only means something postflop.
        ps['is_overbet'] = bool(_call > 0 and _pot_before > 0
                                and _call > _pre_bet
                                and ps.get('street') != 'preflop')
        line = ('%s: call %.1f BB into %.1f BB — need %.1f%%'
                % (ps['street'], _call, _pot_before, ps['required_eq_pct']))
        if ps['is_overbet'] and ps['bet_pct_of_pot'] is not None:
            line += ' — OVERBET %d%% pot' % ps['bet_pct_of_pot']
        elif ps['is_overbet']:
            line += ' — OVERBET'
        summary.append(line)

    # Headline = the most expensive decision (max required equity).
    head = max(per_street, key=lambda p: p.get('required_eq_pct') or 0)
    return {
        'mode': 'street_calls',
        'street': head['street'],
        'call_bb': head['call_bb'],
        'pot_bb': head['total_pot_bb'],
        'pot_before_call_bb': head['pot_before_call_bb'],
        'pot_odds': ('%.2f : 1' % (head['pot_before_call_bb']
                                   / head['call_bb'])
                     if head['call_bb'] else None),
        'required_eq_pct': head['required_eq_pct'],
        'is_overbet': head['is_overbet'],
        'bet_pct_of_pot': head['bet_pct_of_pot'],
        'per_street_calls': per_street,
        'per_street_summary': summary,
        'equity_mode': 'not_computed',
        'equity_note': ('Non-all-in calldown — required equity per street '
                        'from the live pot; no range equity computed.'),
    }


# ---------------------------------------------------------------------------
# BUG-7: Multiway pot detection — main/side pot split
# ---------------------------------------------------------------------------
def _detect_multiway_allin(raw_hh, hero_name='Hero'):
    """Detect multiway pots with all-in players creating main/side pot splits.

    Returns a dict with multiway flags, or None if not a multiway all-in pot.
    """
    if not raw_hh:
        return None
    raw = raw_hh.replace(',', '')

    # Find all players who went all-in (any street)
    allin_players = set()
    for m in re.finditer(r'(\S+):\s+(?:calls|bets|raises).*all-in', raw):
        allin_players.add(m.group(1))

    if len(allin_players) < 1:
        return None  # need at least 1 all-in for main/side pot split

    # Check for side pot indicators in the summary
    has_side_pot = bool(re.search(r'Side pot', raw, re.IGNORECASE))
    has_main_pot = bool(re.search(r'Main pot', raw, re.IGNORECASE))

    if not (has_side_pot or has_main_pot):
        # Multiple all-ins but no pot split — same effective stacks
        return None

    # Parse main pot and side pot amounts
    main_pot = 0.0
    side_pots = []
    for m in re.finditer(r'Main pot\s+(\d+)', raw):
        main_pot = float(m.group(1))
    for m in re.finditer(r'Side pot(?:\s*\d*)?\s+(\d+)', raw):
        side_pots.append(float(m.group(1)))

    # Get BB for conversion
    bb_m = re.search(r'Level\d+\((\d+)/(\d+)', raw)
    bb = float(bb_m.group(2)) if bb_m else 1.0

    # Check if Hero folded (Hero did NOT go to showdown and is not all-in)
    hero_folded = bool(re.search(rf'{re.escape(hero_name)}:\s+folds', raw))
    hero_allin = hero_name in allin_players

    return {
        'n_allins': len(allin_players),
        'has_main_side_split': True,
        'main_pot_bb': round(main_pot / bb, 1) if bb > 0 else 0,
        'side_pot_bb': [round(sp / bb, 1) for sp in side_pots] if bb > 0 else [],
        'hero_folded_side_pot': hero_folded and not hero_allin,
        'allin_players': sorted(allin_players),
    }


# ---------------------------------------------------------------------------
# BUG-4: Multiway showdown decomposition — per-opponent equity
# ---------------------------------------------------------------------------
def multiway_showdown_decomposition(raw_hh, hero_name='Hero'):
    """For multiway showdowns (3+ players), decompose Hero's result
    per-opponent: equity vs each shown hand, who won, suckout detection.

    Returns a dict with per-opponent results, or None if not multiway.
    """
    if not raw_hh or not _PHEV_OK:
        return None
    raw = raw_hh.replace(',', '')

    # Hero cards
    hc = re.search(rf'Dealt to {re.escape(hero_name)} \[(\w\w) (\w\w)\]', raw)
    if not hc:
        return None
    hero_cards = [hc.group(1), hc.group(2)]

    # All shown hands at showdown
    shown = []
    for m in re.finditer(r'(\S+):\s+show(?:s|ed)\s+\[(\w\w) (\w\w)\]', raw):
        if m.group(1) != hero_name:
            shown.append({'player': m.group(1), 'cards': [m.group(2), m.group(3)]})
    if len(shown) < 2:
        return None  # need 2+ opponents for multiway

    # Board
    board = []
    bm = re.search(r'Board \[([2-9TJQKA cdhs]+)\]', raw)
    if bm:
        board = bm.group(1).split()

    # Find all-in street (for equity computation at decision point)
    # Use the board at the all-in point, not the final board
    allin_street = 'preflop'
    for marker, label in (('*** FLOP ***', 'flop'),
                          ('*** TURN ***', 'turn'),
                          ('*** RIVER ***', 'river')):
        # Find earliest all-in action
        idx = raw.find(marker)
        for am in re.finditer(r'all-in', raw):
            if 0 <= idx < am.start():
                allin_street = label
                break

    street_cards = {'preflop': 0, 'flop': 3, 'turn': 4, 'river': 5}
    board_at_allin = board[:street_cards.get(allin_street, 0)]

    # Compute per-opponent equity
    opponents = []
    for v in shown:
        eq = enumerate_equity(hero_cards, [v['cards']], board_at_allin)
        opponents.append({
            'player': v['player'],
            'cards': ''.join(v['cards']),
            'hero_equity_vs_this': eq,
            'hero_ahead': eq is not None and eq > 50.0,
        })

    # Field equity (vs all opponents together)
    all_villain_hands = [v['cards'] for v in shown]
    field_eq = enumerate_equity(hero_cards, all_villain_hands, board_at_allin)

    # Who won the pot?
    winner = None
    for m in re.finditer(r'(\S+)\s+(?:collected|won)\s+\(?\d', raw):
        name = m.group(1)
        if name != hero_name:
            winner = name
            break  # first non-hero collector

    # Hero won?
    hero_won = bool(re.search(
        rf'{re.escape(hero_name)} (?:collected|wins)', raw)) or bool(
        re.search(rf'Seat \d+: {re.escape(hero_name)}[^\n]*\bwon\b', raw))

    # Detect suckout: Hero was ahead vs field (>50%) but lost
    is_suckout = field_eq is not None and field_eq > 50.0 and not hero_won

    # Which opponent beat Hero?
    lost_to = None
    if not hero_won and winner:
        for opp in opponents:
            if opp['player'] == winner:
                lost_to = opp
                break

    # Build narrative
    ahead_of = [o for o in opponents if o['hero_ahead']]
    behind_against = [o for o in opponents if not o['hero_ahead']]
    narrative_parts = []
    if ahead_of:
        ahead_names = ', '.join(f"{o['player']} ({o['cards']}, {o['hero_equity_vs_this']:.0f}%)"
                                for o in ahead_of)
        narrative_parts.append(f"Hero ahead of {ahead_names}")
    if lost_to:
        narrative_parts.append(
            f"lost to {lost_to['player']}'s {lost_to['cards']}"
            f" (Hero had {lost_to['hero_equity_vs_this']:.0f}% vs this hand)")
    if is_suckout:
        narrative_parts.append(f"SUCKOUT — Hero was {field_eq:.0f}% vs field at all-in")

    return {
        'n_opponents': len(shown),
        'hero_cards': ''.join(hero_cards),
        'board_at_allin': board_at_allin,
        'allin_street': allin_street,
        'field_equity': field_eq,
        'per_opponent': opponents,
        'hero_won': hero_won,
        'is_suckout': is_suckout,
        'winner': winner,
        'lost_to': lost_to,
        'narrative': '; '.join(narrative_parts) if narrative_parts else 'multiway showdown',
    }


# ---------------------------------------------------------------------------
# HH integrity — does the recorded result match the cards?
# ---------------------------------------------------------------------------
def integrity_check(hero_cards, villain_hands, board_final, hero_won):
    """Re-evaluate the showdown with phevaluator; return a flag string when
    the computed winner contradicts the recorded result, else None.

    Catches genuinely corrupt anonymised exports — NOT a substitute for
    counting the board correctly (4-to-a-flush is a draw, not a flush)."""
    if not _PHEV_OK or len(board_final) != 5 or not villain_hands:
        return None
    try:
        hero_rank = evaluate_cards(*hero_cards, *board_final)
        vill_ranks = [evaluate_cards(*v, *board_final) for v in villain_hands]
    except Exception:
        return None
    best_v = min(vill_ranks)
    computed_hero_wins = hero_rank < best_v
    computed_tie = hero_rank == best_v
    if computed_tie:
        return None                       # chops — net sign is ambiguous
    if computed_hero_wins != bool(hero_won):
        return ('RESULT MISMATCH: phevaluator scores the showdown '
                f"{'Hero' if computed_hero_wins else 'villain'}-win, but the "
                f"hand is recorded as a {'win' if hero_won else 'loss'} for "
                'Hero — possible corrupt hole-card / board data.')
    return None


# ---------------------------------------------------------------------------
# Per-hand pot-odds block
# ---------------------------------------------------------------------------
def compute_hand_pot_odds(hand, raw_hh):
    """Build the pot_odds block for one hand. Returns the block dict, or None
    if the hand is not a reconstructable all-in call."""
    ctx = reconstruct_allin_call(raw_hh)
    if not ctx:
        return None

    # ---- BUG-5: Shown-hand equity (result-derived, for reference ONLY) ----
    realized_equity = None
    realized_mode = 'unavailable'
    realized_note = ''
    if ctx['villain_hands']:
        realized_equity = enumerate_equity(ctx['hero_cards'], ctx['villain_hands'],
                                           ctx['board_at_decision'])
        if realized_equity is not None:
            realized_mode = 'exact_vs_shown'
            n_v = len(ctx['villain_hands'])
            realized_note = (f"RESULT-DERIVED: exact vs {n_v} shown hand"
                             f"{'s' if n_v != 1 else ''}, "
                             f"{ctx['street']} run-out enumerated. "
                             f"Do NOT use for decision grading.")
    else:
        realized_note = 'villain did not show'

    # ---- BUG-5: Range-based equity (decision-time faithful) ----
    # Determine villain's effective stack for range selection.
    # Priority: jammer_stack_bb (parser-set for preflop jams) > eff_stack_bb
    # > to_call_bb (rough estimate from the pot geometry)
    eff_bb = (hand.get('jammer_stack_bb') or 0)
    if eff_bb <= 0:
        eff_bb = hand.get('eff_stack_bb') or hand.get('effective_stack_bb') or 0
    if eff_bb <= 0:
        eff_bb = ctx['to_call_bb']  # fallback: call amount ≈ villain's shove

    range_equity, range_mode, range_note = compute_range_equity(
        ctx['hero_cards'], ctx['board_at_decision'], eff_bb, ctx['street'])

    villain_range_spec = None
    if ctx['street'] == 'preflop' and len(ctx['board_at_decision']) == 0:
        villain_range_spec = _bucket_spec(_JAM_RANGE_BUCKETS, eff_bb)

    # ---- BUG-7 (moved up in v8.12.0): multiway detection feeds the bounty
    # gate below, so it must run before the discount is computed.
    multiway = None
    try:
        multiway = _detect_multiway_allin(raw_hh)
    except Exception:
        pass

    # ---- Bounty adjustment ----
    bounty = None
    discount_pp = 0.0
    bounty_caveat = ''
    if _BOUNTY_OK:
        bounty = gem_bounty.bounty_context(
            hand.get('tournament', ''), hand.get('tournament_phase', ''),
            fmt=hand.get('format'), hero_covers=ctx['hero_covers_all'])
        discount_pp = bounty['discount_pp']
        # v8.12.0 removals (review guardrails): numeric bounty discounts are
        # unsupported for mystery (value/stage unknown) and for multiway
        # all-ins (research deltas are HU-derived). Those spots keep the
        # bounty CONTEXT for display but get no numeric equity discount and
        # route to Review via the caveat. Never restored on failure paths.
        if (hand.get('format') or '').upper() == 'MYSTERY_BOUNTY':
            if discount_pp > 0:
                bounty_caveat = ('Mystery bounty — value/stage unknown; no '
                                 'numeric discount applied (Review cue).')
            discount_pp = 0.0
        elif multiway:
            if discount_pp > 0:
                bounty_caveat = ('Multiway all-in — HU-derived bounty '
                                 'discount unsupported; no numeric discount '
                                 'applied (Review cue).')
            discount_pp = 0.0
        # v8.12.1 C1: depth-scale the surviving HU-covering discount
        # (authoritative per the S4.4 migration audit review).
        if discount_pp > 0:
            _pk_scale = 1.0 if (eff_bb or 0) <= 20 else (
                0.5 if (eff_bb or 0) <= 35 else 0.25)
            discount_pp = round(discount_pp * _pk_scale, 1)

    required = ctx['required_eq_pct']
    # v8.12.8 QA3 (66662469): multiway all-in where Hero does NOT cover the
    # field — GG's final Total pot includes a side pot Hero can't win, so
    # pricing against it UNDERSTATES required equity (26.1% rendered where
    # the main-pot price is 31%). When the summary prints a Main pot line,
    # the covered hero's price is to_call / main_pot.
    required_eq_note = ''
    main_pot_bb = None
    if (not ctx['hero_covers_all']) and ctx['n_players_at_showdown'] >= 3:
        _mp_m = re.search(r'Main pot\s+(\d+)', raw_hh.replace(',', ''))
        if _mp_m:
            _mp_bb = float(_mp_m.group(1)) / ctx['bb']
            if 0 < _mp_bb < ctx['total_pot_bb'] and ctx['to_call_bb'] > 0:
                main_pot_bb = round(_mp_bb, 1)
                required = round(ctx['to_call_bb'] / _mp_bb * 100.0, 1)
                required_eq_note = (
                    f'priced on the main pot ({main_pot_bb} BB) — the '
                    f'{round(ctx["total_pot_bb"] - _mp_bb, 1)} BB side pot '
                    'is between the covering stacks; Hero cannot win it')
    required_bounty = round(max(0.0, required - discount_pp), 1)

    # ---- Verdict gated on RANGE equity only (BUG-5 fix) ----
    ev_call_bb = None
    ev_call_bounty_bb = None
    verdict_hint = 'range unavailable — do not grade on result'

    # Use whichever equity is available: range first, then shown-hand fallback
    _eq_for_verdict = range_equity if range_equity is not None else (
        realized_equity if realized_equity is not None else None)
    _eq_source = 'vs range' if range_equity is not None else 'vs shown'
    if _eq_for_verdict is not None:
        # v8.12.8 QA3: EV must also price the winnable pot only
        _pot_for_ev = main_pot_bb if main_pot_bb else ctx['total_pot_bb']
        ev_call_bb = round(_eq_for_verdict / 100.0 * _pot_for_ev
                           - ctx['to_call_bb'], 1)
        ev_call_bounty_bb = round(
            ev_call_bb + (discount_pp / 100.0) * _pot_for_ev, 1)
        eff_required = required_bounty if discount_pp > 0 else required
        margin = _eq_for_verdict - eff_required
        if margin >= 1.5:
            verdict_hint = f'call +EV {_eq_source}'
        elif margin <= -1.5:
            verdict_hint = f'call -EV {_eq_source}'
        else:
            verdict_hint = f'borderline {_eq_source} (within 1.5pp)'

    flag = integrity_check(ctx['hero_cards'], ctx['villain_hands'],
                           ctx['board_final'], ctx['hero_won'])

    # ---- BUG-6: Per-street call detection ----
    per_street = []
    root_street = None
    try:
        per_street = _parse_per_street_calls(raw_hh, ctx['bb'])
        if per_street and len(per_street) > 1:
            # Root decision street = earliest street where the call was large
            # relative to the pot (required equity > 30% is standard for
            # -EV territory in bounty formats)
            for ps in per_street:
                if ps['required_eq_pct'] > 30:
                    root_street = ps['street']
                    break
    except Exception:
        pass

    # ---- BUG-7: Multiway pot detection ----
    # v8.12.0: detection moved ABOVE the bounty adjustment (the discount gate
    # needs it); `multiway` is already populated here.

    # W3: when range equity is unavailable but shown-hand equity exists,
    # use it as the analyst-facing equity. For all-in-to-showdown hands
    # the realized equity IS what the analyst needs for §3b math.
    _analyst_eq = range_equity
    _analyst_mode = range_mode
    _analyst_note = range_note
    if _analyst_eq is None and realized_equity is not None:
        _analyst_eq = realized_equity
        _analyst_mode = 'exact_vs_shown'
        _analyst_note = ('Equity vs shown villain hand(s) — '
                         'use for §3b math on all-in-to-showdown spots')

    block = {
        'street': ctx['street'],
        'call_bb': ctx['to_call_bb'],
        'pot_bb': ctx['total_pot_bb'],
        'pot_before_call_bb': ctx['pot_before_call_bb'],
        'pot_odds': f"{ctx['pot_before_call_bb'] / ctx['to_call_bb']:.2f} : 1",
        'required_eq_pct': required,
        'required_eq_note': required_eq_note,
        'main_pot_bb': main_pot_bb,
        # Analyst-facing equity: range when available, shown when not
        'hero_equity_pct': _analyst_eq,
        'equity_mode': _analyst_mode,
        'equity_note': _analyst_note,
        # BUG-5: Shown-hand equity (result-derived, reference only)
        'realized_equity_vs_shown': realized_equity,
        'realized_equity_mode': realized_mode,
        'realized_equity_note': realized_note,
        # Verdict gated on range equity
        'ev_call_bb': ev_call_bb,
        'verdict_hint': verdict_hint,
        'hero_covers_field': ctx['hero_covers_all'],
        'n_players_at_showdown': ctx['n_players_at_showdown'],
        'villain_range_spec': villain_range_spec,
    }

    if bounty and discount_pp > 0:
        block['bounty'] = bounty
        block['required_eq_bounty_pct'] = required_bounty
        block['ev_call_bounty_bb'] = ev_call_bounty_bb
    elif bounty:
        block['bounty'] = bounty
    if bounty_caveat:
        block['bounty_caveat'] = bounty_caveat

    if flag:
        block['integrity_flag'] = flag

    # BUG-6: per-street call data
    if per_street:
        block['per_street_calls'] = per_street
    if root_street and root_street != ctx['street']:
        block['root_decision_street'] = root_street

    # BUG-7: multiway flag
    if multiway:
        block['multiway_flag'] = multiway

    return block


# ---------------------------------------------------------------------------
# BUG-7: Multiway over-fold detector — find hands where Hero folded in a
# side pot while having equity in the main pot
# ---------------------------------------------------------------------------
def detect_multiway_overfold(hand, raw_hh):
    """Detect when Hero folded to a side-pot bet while having significant
    equity in the main pot (forfeiting main-pot claim).

    Returns a dict with over-fold context, or None.
    """
    if not raw_hh or not _PHEV_OK:
        return None

    raw = raw_hh.replace(',', '')
    hero_name = 'Hero'

    # Must be a hand where Hero folded
    if not re.search(rf'{re.escape(hero_name)}:\s+folds', raw):
        return None

    # Must have a main/side pot split (multiway with all-in short)
    multiway = _detect_multiway_allin(raw_hh, hero_name)
    if not multiway or not multiway.get('has_main_side_split'):
        return None
    if not multiway.get('hero_folded_side_pot'):
        return None

    # Hero cards
    hc = re.search(rf'Dealt to {re.escape(hero_name)} \[(\w\w) (\w\w)\]', raw)
    if not hc:
        return None
    hero_cards = [hc.group(1), hc.group(2)]

    # Board at fold point — find the street where hero folded
    fold_m = re.search(rf'{re.escape(hero_name)}:\s+folds', raw)
    if not fold_m:
        return None
    fold_pos = fold_m.start()
    fold_street = 'preflop'
    for marker, label in (('*** FLOP ***', 'flop'),
                          ('*** TURN ***', 'turn'),
                          ('*** RIVER ***', 'river')):
        idx = raw.find(marker)
        if 0 <= idx < fold_pos:
            fold_street = label

    # Board at fold
    board_final = []
    bm = re.search(r'Board \[([2-9TJQKA cdhs]+)\]', raw)
    if bm:
        board_final = bm.group(1).split()
    street_cards = {'preflop': 0, 'flop': 3, 'turn': 4, 'river': 5}
    board_at_fold = board_final[:street_cards.get(fold_street, 0)]

    # Get the all-in short player's hand (if shown)
    # The short player is the one who created the main pot
    allin_villain_hands = []
    for m in re.finditer(r'(\S+):\s+show(?:s|ed)\s+\[(\w\w) (\w\w)\]', raw):
        if m.group(1) != hero_name:
            allin_villain_hands.append([m.group(2), m.group(3)])

    # Compute Hero's equity vs all shown hands (for the main pot)
    equity_at_fold = None
    if allin_villain_hands and board_at_fold:
        equity_at_fold = enumerate_equity(hero_cards, allin_villain_hands,
                                          board_at_fold)

    bb_m = re.search(r'Level\d+\((\d+)/(\d+)', raw)
    bb = float(bb_m.group(2)) if bb_m else 1.0

    return {
        'fold_street': fold_street,
        'hero_cards': hero_cards,
        'board_at_fold': board_at_fold,
        'hero_equity_at_fold_pct': equity_at_fold,
        'main_pot_bb': multiway['main_pot_bb'],
        'n_allins': multiway['n_allins'],
        'forfeited_ev_bb': round(equity_at_fold / 100.0 * multiway['main_pot_bb'], 1)
            if equity_at_fold is not None else None,
    }


# ---------------------------------------------------------------------------
# Candidate enrichment — entry point for the pipeline
# ---------------------------------------------------------------------------
def _load_raw_hh(hand_ids, hh_dir):
    """{id: raw_hh_text} for the requested ids, scanning the HH directory."""
    found = {}
    if not hh_dir:
        return found
    import os
    want = set(hand_ids)
    try:
        files = [os.path.join(hh_dir, fn) for fn in os.listdir(hh_dir)
                 if fn.lower().endswith('.txt')]
    except Exception:
        return found
    for fp in files:
        try:
            with open(fp, encoding='utf-8', errors='replace') as f:
                text = f.read()
        except Exception:
            continue
        # GG hands are separated by "Poker Hand #..." headers.
        for chunk in re.split(r'(?=Poker Hand #)', text):
            hm = re.match(r'Poker Hand #(\S+?):', chunk)
            if hm and hm.group(1) in want:
                found[hm.group(1)] = chunk
        if len(found) >= len(want):
            break
    return found


def enrich_candidates(candidates, hands, hh_dir):
    """Attach a `pot_odds` block to every candidate hand that is a
    reconstructable all-in call. Mutates `candidates` in place and returns a
    small stats dict. Never raises — pot-odds enrichment must not be able to
    break candidate generation.

    `candidates` is the analyst_candidates dict (buckets of hand-ctx lists).
    """
    stats = {'enriched': 0, 'integrity_flags': 0, 'skipped': 0,
             'range_equity': 0, 'multiway_flags': 0,
             'per_street': 0, 'overfold_flags': 0, 'street_calls': 0}
    # v8.12.8: the non-all-in street-calls path is pure pot arithmetic and
    # must run even without the equity engine — only the all-in/equity
    # paths are gated on phevaluator.
    if not _PHEV_OK:
        stats['note'] = ('phevaluator unavailable — all-in equity '
                         'enrichment skipped (street-call pot odds still '
                         'computed)')

    hands_by_id = {h.get('id'): h for h in hands}
    # Collect every candidate ctx across all buckets, de-duplicated by id.
    bucket_keys = ('bust_audit', 'coolers', 'mistakes', 'punts',
                   'iii4_screening', 'read_dependent_screening',
                   'bestplay_screening')
    ctx_by_id = {}
    for key in bucket_keys:
        for ctx in candidates.get(key, []) or []:
            if isinstance(ctx, dict) and ctx.get('id'):
                ctx_by_id.setdefault(ctx['id'], []).append(ctx)

    if not ctx_by_id:
        return stats
    raw_map = _load_raw_hh(list(ctx_by_id.keys()), hh_dir)

    # EFFICIENCY #6: parallel equity computation when enough candidates.
    # Each hand's MC equity is independent — parallelize across hands.
    def _compute_one(hid):
        raw = raw_map.get(hid)
        if not raw:
            return hid, None, 'skip'
        try:
            block = compute_hand_pot_odds(hands_by_id.get(hid, {}), raw)
        except Exception:
            block = None
        return hid, block, 'ok' if block else 'skip'

    _n_to_process = len(ctx_by_id)
    _USE_PARALLEL = _n_to_process >= 10
    if _USE_PARALLEL:
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(8, _n_to_process)) as _pool:
                _results = list(_pool.map(_compute_one, ctx_by_id.keys()))
        except Exception:
            _results = [_compute_one(hid) for hid in ctx_by_id]
    else:
        _results = [_compute_one(hid) for hid in ctx_by_id]

    for hid, block, status in _results:
        if status == 'skip' or not block:
            stats['skipped'] += 1
            continue
        for ctx in ctx_by_id[hid]:
            ctx['pot_odds'] = block
        stats['enriched'] += 1
        if block.get('integrity_flag'):
            stats['integrity_flags'] += 1
        if block.get('equity_mode') == 'range_mc':
            stats['range_equity'] += 1
        if block.get('multiway_flag'):
            stats['multiway_flags'] += 1
        if block.get('per_street_calls'):
            stats['per_street'] += 1

    # v8.12.8 (handover Issue 1): SECOND PATH — non-all-in bet-facing calls.
    # The all-in reconstructor returns None for these, so the deep
    # multi-street overbet calldowns (the spots a human misjudges) carried
    # no required-equity number into the worksheet. Pure arithmetic — runs
    # regardless of the equity engine.
    for hid, ctx_list in ctx_by_id.items():
        if any(c.get('pot_odds') for c in ctx_list):
            continue  # all-in block already attached
        raw = raw_map.get(hid)
        if not raw:
            continue
        try:
            _sc_blk = compute_nonallin_pot_odds(hands_by_id.get(hid, {}), raw)
        except Exception:
            _sc_blk = None
        if _sc_blk:
            for c in ctx_list:
                c['pot_odds'] = _sc_blk
            stats['street_calls'] += 1

    # BUG-4: multiway showdown decomposition for bust-audit candidates.
    # For multiway all-ins, decompose per-opponent equity so the audit
    # shows "Hero ahead of [A] (X%), lost to [C]'s [hand]" instead of
    # flat "SD lost."
    stats['multiway_decomp'] = 0
    for ctx_list in ctx_by_id.values():
        for ctx in ctx_list:
            hid = ctx.get('id', '')
            raw = raw_map.get(hid)
            if not raw:
                continue
            try:
                decomp = multiway_showdown_decomposition(raw)
            except Exception:
                decomp = None
            if decomp and decomp.get('n_opponents', 0) >= 2:
                ctx['multiway_decomposition'] = decomp
                stats['multiway_decomp'] += 1

    # BUG-7: scan ALL hands (not just candidates) for multiway over-folds
    # that the existing candidate builder missed entirely.
    overfold_candidates = []
    for h in hands:
        hid = h.get('id')
        if not hid or hid in ctx_by_id:
            continue  # already a candidate
        raw = raw_map.get(hid)
        if not raw:
            # Need to load this hand's HH
            continue
        try:
            of = detect_multiway_overfold(h, raw)
        except Exception:
            of = None
        if of and of.get('hero_equity_at_fold_pct') is not None:
            # Significant over-fold: hero had >25% equity in the main pot
            if of['hero_equity_at_fold_pct'] >= 25:
                overfold_candidates.append({
                    'id': hid,
                    'multiway_overfold': of,
                })
                stats['overfold_flags'] += 1

    # Add over-fold candidates to the bust_audit bucket if they qualify
    if overfold_candidates:
        for ofc in overfold_candidates:
            hid = ofc['id']
            h = hands_by_id.get(hid)
            if h:
                ctx = {
                    'id': hid,
                    'tournament': h.get('tournament'),
                    'date': h.get('date'),
                    'position': h.get('position'),
                    'stack_bb': h.get('stack_bb'),
                    'cards': ''.join(h.get('cards', [])),
                    'board': h.get('board', ''),
                    'net_bb': h.get('net_bb', 0),
                    'action_summary': h.get('action_summary', ''),
                    'n_players': h.get('n_players'),
                    'multiway_overfold': ofc['multiway_overfold'],
                    'note': 'BUG-7: multiway over-fold — Hero folded to '
                            'side-pot bet while holding main-pot equity',
                }
                candidates.setdefault('bust_audit', []).append(ctx)

    return stats
