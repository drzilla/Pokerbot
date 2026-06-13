#!/usr/bin/env python3
"""
coinpoker_to_gg.py — Transform CoinPoker XML hand histories into the
GG-text format that gem_parser.py consumes.

Key correctness points (these are what broke last time → "??" positions):
  * Button seat = <DealerButtonPosition> (verified to always be an
    occupied seat across the whole batch).
  * Positions are NOT emitted by us — the GG parser derives them by
    walking occupied seats clockwise from the button. We only need to
    emit a correct "Seat #N is the button" line, the real Seat list
    (preserving CoinPoker SeatNumber, gaps included), and the
    SB/BB post lines. Verified: parser-derived SB/BB == CoinPoker's
    own SMALL_BLIND/BIG_BLIND labels on 3401/3401 hands.

Amount semantics (CoinPoker):
  * RAISE / BET Amount = the street TOTAL the actor's wager reaches
    (e.g. open to 3500 -> RAISE -3500; 3-bet to 8400 -> RAISE -8400).
  * CALL Amount = the INCREMENT the caller adds this action.
  * BLIND / ANTE Amount = chips posted (negative).
  * UNCALLED_BET Amount = chips returned (positive).
  * ALL_IN behaves like BET/RAISE total; IsAllIn flag also set on the
    triggering BET/RAISE/CALL.

GG-text targets:
  * Open/raise  -> "Name: raises <inc> to <total>[ and is all-in]"
  * Bet         -> "Name: bets <total>[ and is all-in]"
  * Call        -> "Name: calls <inc>[ and is all-in]"
  * Check/Fold  -> "Name: checks" / "Name: folds"
  * Blinds      -> "Name: posts small blind X" / "...big blind X"
  * Antes       -> "Name: posts the ante X"
  * Uncalled    -> "Uncalled bet (X) returned to Name"
  * Wins        -> "Name collected X from pot"
"""
import re, glob, os, sys
from xml.etree import ElementTree as ET

HERO = "DCB1316"

def _num(x):
    """CoinPoker amount string -> rounded int chips (drop sign)."""
    v = abs(float(x))
    return int(round(v))

def _fmt(n):
    return str(int(n))

def parse_hands(raw):
    out = []
    for blk in re.split(r'(?=<\?xml)', raw):
        if '<HandHistory>' in blk:
            out.append(blk)
    return out

def split_board(cards_str):
    """'Qc3hQd9hKs' -> ['Qc','3h','Qd','9h','Ks']"""
    cs = cards_str.strip()
    return [cs[i:i+2] for i in range(0, len(cs), 2)] if cs else []

def transform_hand(xml_text):
    # strip BOM / leading whitespace before XML decl for ET
    t = xml_text[xml_text.find('<HandHistory'):]
    root = ET.fromstring(t)

    hand_id = root.findtext('HandId')
    btn_seat = int(root.findtext('DealerButtonPosition'))
    gd = root.find('GameDescription')
    limit = gd.find('Limit')
    sb = _num(limit.findtext('SmallBlind'))
    bb = _num(limit.findtext('BigBlind'))
    ante = _num(limit.findtext('Ante') or 0)
    seat_type = gd.find('SeatType')
    max_players = int(seat_type.get('MaxPlayers')) if seat_type is not None else 0

    tour = gd.find('Tournament')
    tid = tour.findtext('TournamentId')
    tname = tour.findtext('TournamentName') or 'Tournament'
    # CoinPoker uses ₮ prefix for buy-in amounts in tournament names.
    # Replace with $ so gem_parser's buy-in regex recognizes the amount
    # (parser looks for \d+\s*(?:USD|€|\$) in the first 200 chars).
    tname = tname.replace('₮', '$')
    date_utc = root.findtext('DateOfHandUtc') or ''
    # 2026-05-30T02:27:25.124... -> 2026/05/30 02:27:25
    dm = re.match(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})', date_utc)
    if dm:
        date_str = f"{dm.group(1)}/{dm.group(2)}/{dm.group(3)} {dm.group(4)}:{dm.group(5)}:{dm.group(6)}"
    else:
        date_str = "2026/05/30 00:00:00"

    # Players / seats
    players = root.find('Players')
    seatmap = {}   # seat_num -> dict
    name_to_seat = {}
    for p in players.findall('Player'):
        sn = int(p.get('SeatNumber'))
        name = p.get('PlayerName')
        stack = _num(p.get('StartingStack'))
        cards = (p.get('Cards') or '').strip()
        seatmap[sn] = {'name': name, 'stack': stack, 'cards': cards}
        name_to_seat[name] = sn

    n_players = len(seatmap)
    # Table-size label for GG: parser reads "<N>-max" from text[:300].
    # Use the real seated count's table size from MaxPlayers when sane,
    # else fall back to seated count. Parser only uses it for chart shift;
    # positions come from seat-walk, so this is cosmetic but keep honest.
    size_label = max_players if max_players >= n_players and max_players in (2,5,6,7,8,9) else n_players

    # Actions
    actions = root.find('Actions')
    acts = []
    for a in actions.findall('HandAction'):
        acts.append({
            'name': a.get('PlayerName'),
            'type': a.get('HandActionType'),
            'amount': a.get('Amount'),
            'street': a.get('Street'),
            'allin': (a.get('IsAllIn') == 'true'),
        })

    board = split_board(root.find('CommunityCards').text or '' if root.find('CommunityCards') is not None and root.find('CommunityCards').text else '')

    # ---- Build GG text ----
    L = []
    # Header. Encode bounty as "Bounty" only if IsKnockout; here all false → plain.
    # Bounty classification: CoinPoker's IsKnockout flag is unreliable here
    # (all hands export false even for PKO events). Per Ron, classify by
    # tournament NAME instead.
    _ko_flag = (tour.find('BuyIn').findtext('IsKnockout') == 'true')
    _name_l = tname.lower()
    is_ko = _ko_flag or any(k in _name_l for k in
        ('bounty', 'pko', 'knockout', ' ko', 'progressive', 'hunter', 'collision'))
    game_label = "Hold'em No Limit"
    # Level token: parser wants LevelX(sb/bb(ante)). We don't have a level number;
    # use a synthetic level derived from blinds index is unnecessary — parser only
    # needs the (sb/bb(ante)) capture. Provide Level0 placeholder with real blinds.
    ko_tag = "Bounty " if is_ko else ""
    L.append(f"Poker Hand #TM{hand_id}: Tournament #{tid}, {tname} {ko_tag}{game_label} - Level1({sb}/{bb}({ante})) - {date_str}")
    L.append(f"Table '{tid}' {size_label}-max Seat #{btn_seat} is the button")

    for sn in sorted(seatmap.keys()):
        info = seatmap[sn]
        L.append(f"Seat {sn}: {info['name']} ({_fmt(info['stack'])} in chips)")

    # Antes (parser counts ante*n_players for dead money; emit per anteing player)
    for a in acts:
        if a['type'] == 'ANTE':
            L.append(f"{a['name']}: posts the ante {_num(a['amount'])}")
    # Blinds
    for a in acts:
        if a['type'] == 'SMALL_BLIND':
            L.append(f"{a['name']}: posts small blind {_num(a['amount'])}")
        elif a['type'] == 'BIG_BLIND':
            L.append(f"{a['name']}: posts big blind {_num(a['amount'])}")

    # Hole cards
    L.append("*** HOLE CARDS ***")
    hero_name = root.findtext('HeroName') or HERO
    hero_cards = seatmap.get(name_to_seat.get(hero_name, -1), {}).get('cards', '')
    if hero_cards:
        hc = split_board(hero_cards)
        L.append(f"Dealt to {hero_name} [{' '.join(hc)}]")
    else:
        # no hero cards (shouldn't happen for hero); still emit a Dealt line
        L.append(f"Dealt to {hero_name} ")

    # Track per-street totals to convert RAISE(total) into "raises inc to total"
    # and to know current bet level. CALL amount is already the increment.
    def emit_street(street_acts, label=None, board_slice=None):
        if label:
            if board_slice is not None:
                L.append(f"*** {label} *** [{' '.join(board_slice)}]" if label == 'FLOP'
                         else f"*** {label} *** [{' '.join(board_slice[:-1])}] [{board_slice[-1]}]")
        street_committed = {}   # name -> chips this street (for raise increment calc)
        current_bet = 0
        # On preflop, blinds already posted into committed
        if label is None:  # preflop
            for a in acts:
                if a['type'] == 'SMALL_BLIND':
                    street_committed[a['name']] = _num(a['amount']); current_bet = max(current_bet, _num(a['amount']))
                elif a['type'] == 'BIG_BLIND':
                    street_committed[a['name']] = _num(a['amount']); current_bet = max(current_bet, _num(a['amount']))
        for a in street_acts:
            nm, ty = a['name'], a['type']
            allin = " and is all-in" if a['allin'] else ""
            if ty in ('ANTE', 'SMALL_BLIND', 'BIG_BLIND'):
                continue
            elif ty == 'FOLD':
                L.append(f"{nm}: folds")
            elif ty == 'CHECK':
                L.append(f"{nm}: checks")
            elif ty in ('RAISE', 'ALL_IN'):
                total = _num(a['amount'])
                inc = total - street_committed.get(nm, 0)
                # RAISE total is the new street level
                L.append(f"{nm}: raises {inc} to {total}{allin}")
                street_committed[nm] = total
                current_bet = total
            elif ty == 'BET':
                total = _num(a['amount'])
                L.append(f"{nm}: bets {total}{allin}")
                street_committed[nm] = street_committed.get(nm, 0) + total
                current_bet = max(current_bet, street_committed[nm])
            elif ty == 'CALL':
                inc = _num(a['amount'])
                L.append(f"{nm}: calls {inc}{allin}")
                street_committed[nm] = street_committed.get(nm, 0) + inc
            elif ty == 'UNCALLED_BET':
                L.append(f"Uncalled bet ({_num(a['amount'])}) returned to {nm}")
            elif ty == 'WINS':
                pass  # handled in summary
        return

    pre = [a for a in acts if a['street'] == 'Preflop']
    flop = [a for a in acts if a['street'] == 'Flop']
    turn = [a for a in acts if a['street'] == 'Turn']
    river = [a for a in acts if a['street'] == 'River']

    emit_street(pre, None)

    if flop and len(board) >= 3:
        emit_street(flop, 'FLOP', board[:3])
    if turn and len(board) >= 4:
        emit_street(turn, 'TURN', board[:4])
    if river and len(board) >= 5:
        emit_street(river, 'RIVER', board[:5])

    wins = [a for a in acts if a['type'] == 'WINS']
    # A REAL showdown occurs iff >=2 players have revealed (non-empty) Cards.
    # CoinPoker always populates the hero's Cards regardless of showdown, so
    # "hero has cards" alone is NOT a showdown — that wrongly tagged every
    # uncontested hero win as a won showdown and inflated WSD to ~100%.
    # The parser keys went_to_sd off "hero ... showed" in the SUMMARY, so we
    # emit "showed"/SHOWDOWN ONLY for genuine multi-player showdowns.
    carded_players = [sn for sn in seatmap if seatmap[sn]['cards']]
    is_showdown = len(carded_players) >= 2
    # The hero reached showdown only if the hero never folded. The hero's Cards
    # are always present in CoinPoker, so we must check the action stream:
    # a hero who folded (even while villains went to showdown) did NOT reach SD.
    hero_folded = any(a['name'] == hero_name and a['type'] == 'FOLD' for a in acts)
    hero_at_showdown = is_showdown and not hero_folded
    if is_showdown:
        L.append("*** SHOWDOWN ***")
        for sn in sorted(seatmap.keys()):
            info = seatmap[sn]
            if info['cards'] and info['name'] != hero_name:
                hc = split_board(info['cards'])
                L.append(f"{info['name']}: shows [{' '.join(hc)}]")
    for a in wins:
        L.append(f"{a['name']} collected {_num(a['amount'])} from pot")

    # Summary
    L.append("*** SUMMARY ***")
    total_pot = _num(root.findtext('TotalPot') or 0)
    L.append(f"Total pot {total_pot} | Rake 0")
    if board:
        if len(board) == 3:
            L.append(f"Board [{' '.join(board)}]")
        elif len(board) == 4:
            L.append(f"Board [{' '.join(board)}]")
        elif len(board) >= 5:
            L.append(f"Board [{' '.join(board[:5])}]")
    win_names = {a['name']: _num(a['amount']) for a in wins}
    for sn in sorted(seatmap.keys()):
        info = seatmap[sn]
        nm = info['name']
        # Did THIS player reach showdown? Hero: only if not folded. Villain:
        # CoinPoker only fills a villain's Cards when they actually showed.
        if nm == hero_name:
            showed_down = hero_at_showdown
        else:
            showed_down = is_showdown and bool(info['cards'])
        if nm in win_names:
            if showed_down and info['cards']:
                hc = split_board(info['cards'])
                L.append(f"Seat {sn}: {nm} showed [{' '.join(hc)}] and won ({win_names[nm]})")
            else:
                L.append(f"Seat {sn}: {nm} collected ({win_names[nm]})")
        else:
            if showed_down and info['cards']:
                hc = split_board(info['cards'])
                L.append(f"Seat {sn}: {nm} showed [{' '.join(hc)}] and lost")
            else:
                L.append(f"Seat {sn}: {nm} folded")

    return "\n".join(L)


def main():
    files = sorted(glob.glob('/mnt/user-data/uploads/dh_exported_file_1*.txt'))
    all_hands = []
    for fp in files:
        raw = open(fp, encoding='utf-8-sig').read()
        all_hands.extend(parse_hands(raw))
    print(f"Parsed {len(all_hands)} CoinPoker hands from {len(files)} files", file=sys.stderr)

    out_blocks = []
    errs = 0
    for i, h in enumerate(all_hands):
        try:
            out_blocks.append(transform_hand(h))
        except Exception as e:
            errs += 1
            if errs <= 5:
                print(f"  err hand {i}: {e}", file=sys.stderr)
    print(f"Transformed {len(out_blocks)} hands, {errs} errors", file=sys.stderr)

    out_path = sys.argv[1] if len(sys.argv) > 1 else '/home/claude/work/dave_DCB1316_gg.txt'
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("\n\n\n".join(out_blocks) + "\n")
    print(f"Wrote {out_path}", file=sys.stderr)

if __name__ == '__main__':
    main()
