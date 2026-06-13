"""
live_to_gg.py — convert live tournament notes to GG-format hand histories
that GTO Wizard can parse.

Design: each hand is a compact dict. The converter handles:
  - Seat assignment from positions + button
  - Auto-fold lines for players who weren't in the action
  - Pot/bet/call amount tracking (you specify intent, not deltas)
  - All-in detection
  - Uncalled bet returns
  - Showdown shows
  - Per-seat summary lines

ACTION DSL (one string per action):
  "<POS>: fold"
  "<POS>: check"
  "<POS>: call"                       # auto-computes call amount
  "<POS>: limp"                       # SB completing preflop
  "<POS>: bet 1500"                   # first agg on a street
  "<POS>: raise 4500"                 # raise TO 4500 total
  "<POS>: shove"                      # all-in for remaining stack
  "<POS>: show Kc Kd"                 # showdown reveal
  "F Kh Js 9c" / "T Td" / "R 8x"      # deal streets
  "WIN <POS>"                         # who collects the pot

POSITIONS (use abbrevs): UTG, UTG1, UTG2, MP, LJ, HJ, CO, BU, SB, BB
"""

POS_BY_SIZE = {
    9: ['UTG','UTG1','MP','LJ','HJ','CO','BU','SB','BB'],
    8: ['UTG','UTG1','MP','HJ','CO','BU','SB','BB'],
    7: ['UTG','MP','HJ','CO','BU','SB','BB'],
    6: ['UTG','HJ','CO','BU','SB','BB'],
    5: ['HJ','CO','BU','SB','BB'],
    4: ['CO','BU','SB','BB'],
    3: ['BU','SB','BB'],
    2: ['SB','BB'],
}

PFAct_ORDER = lambda layout: layout  # already in PF action order: UTG → BB

def fmt(n): return f"{n:,}"

class Player:
    def __init__(self, pos, seat, name, chips, hole=None):
        self.pos = pos; self.seat = seat; self.name = name
        self.start_chips = chips; self.chips = chips
        self.hole = hole
        self.folded = False
        self.in_pot = 0          # total chips committed across all streets
        self.committed = 0       # chips committed THIS street
        self.allin = False
        self.last_active_street = None  # 'pf','flop','turn','river'
        self.shown = False
        self.shown_desc = None

class Hand:
    def __init__(self, hand_id, tourney_id, buyin, level, sb, bb, ante,
                 dt, table, n, btn_pos, day_id):
        self.meta = dict(hand_id=hand_id, tourney_id=tourney_id, buyin=buyin,
                         level=level, sb=sb, bb=bb, ante=ante, dt=dt,
                         table=table, n=n, btn_pos=btn_pos)
        self.layout = POS_BY_SIZE[n]
        self.players = {}     # pos -> Player
        # Assign seats: button at the seat = layout.index('BU')+1 in 9-max etc.
        # Simplest: seat = layout-index + 1, irrespective of btn_pos label.
        # The btn marker in the table line uses the seat at btn_pos.
        for i, pos in enumerate(self.layout):
            self.players[pos] = Player(pos, i+1, None, 0)
        self.btn_seat = self.layout.index(btn_pos) + 1
        self.day_id = day_id
        self.action_lines = {'pf': [], 'flop': [], 'turn': [], 'river': []}
        self.cur_street = 'pf'
        self.cur_bet = 0
        self.last_agg_pos = None
        self.flop = self.turn = self.river = None
        self.uncalled_amt = 0
        self.uncalled_pos = None
        self.winner_pos = None
        self.split_winners = None  # list of pos strings if pot was chopped
        self.shows_inline = {'pf':[],'flop':[],'turn':[],'river':[]}

    def add_player(self, pos, chips, hole=None, name=None):
        p = self.players[pos]
        p.start_chips = p.chips = chips
        p.hole = hole
        if name:
            p.name = name
        else:
            # auto-name: "lv<day><pos>" with day_id and a position-based suffix
            short = {'UTG':'utg','UTG1':'ut1','UTG2':'ut2','MP':'mp_','LJ':'lj_',
                     'HJ':'hj_','CO':'co_','BU':'btn','SB':'sb_','BB':'bb_'}[pos]
            p.name = f"{self.day_id}{short}"  # e.g. "01asb_"

    def fill_villains(self, hero_pos, hero_chips, default_chips, custom_chips=None):
        """Auto-fill all non-hero seats with default_chips unless overridden."""
        custom_chips = custom_chips or {}
        for pos, p in self.players.items():
            if pos == hero_pos: continue
            chips = custom_chips.get(pos, default_chips)
            self.add_player(pos, chips)

    def post_blinds_antes(self):
        # Happens before action lines; we render these first.
        ante = self.meta['ante']
        if ante > 0:
            for pos in self.layout:
                p = self.players[pos]
                p.in_pot += ante
                p.chips -= ante
        sb_p = self.players['SB']
        sb_p.in_pot += self.meta['sb']
        sb_p.committed = self.meta['sb']
        sb_p.chips -= self.meta['sb']
        bb_p = self.players['BB']
        bb_p.in_pot += self.meta['bb']
        bb_p.committed = self.meta['bb']
        bb_p.chips -= self.meta['bb']
        self.cur_bet = self.meta['bb']

    def reset_street(self, street):
        self.cur_street = street
        self.cur_bet = 0
        self.last_agg_pos = None
        for p in self.players.values():
            p.committed = 0

    def execute(self, dsl_lines):
        """Run a list of action DSL strings."""
        # Filter blank lines
        lines = [l.strip() for l in dsl_lines if l.strip()]
        # Implicit: all positions before the first listed actor on PF that aren't in actions = fold
        # But to keep things simple, the spec must list every PF action explicitly OR mark "FOLDS_TO X".
        # We'll handle via "FOLDS_TO <pos>" pseudo-action that auto-folds prior positions.
        i = 0
        while i < len(lines):
            line = lines[i]
            tok = line.split()
            if line.startswith('FOLDS_TO '):
                target = tok[1]
                # fold every position from current point to before target (in PF order)
                already_acted = set()
                for la in self.action_lines['pf']:
                    # parse player name from front
                    nm = la.split(':')[0]
                    for pp in self.players.values():
                        if pp.name == nm:
                            already_acted.add(pp.pos); break
                for pos in self.layout:
                    if pos == target: break
                    if pos in ('SB','BB'): continue  # they have blinds, not folded yet
                    if pos in already_acted: continue
                    p = self.players[pos]
                    p.folded = True
                    p.last_active_street = 'pf'
                    self.action_lines['pf'].append(f"{p.name}: folds")
            elif line.startswith('FOLDS_TO_HERO'):
                # fold all positions before Hero (in PF order, skipping SB/BB/Hero)
                hero_pos = tok[1]
                for pos in self.layout:
                    if pos == hero_pos: break
                    if pos in ('SB','BB'): continue
                    p = self.players[pos]
                    if not p.folded:
                        p.folded = True
                        p.last_active_street = 'pf'
                        self.action_lines['pf'].append(f"{p.name}: folds")
            elif line.startswith('FOLDS_REMAINING'):
                # everyone else (not Hero, not target list) folds in PF order
                survivors = set(tok[1:])
                for pos in self.layout:
                    if pos in survivors: continue
                    p = self.players[pos]
                    if not p.folded and not p.allin:
                        p.folded = True
                        p.last_active_street = self.cur_street
                        self.action_lines[self.cur_street].append(f"{p.name}: folds")
            elif line.startswith('F '):
                cards = ' '.join(tok[1:])
                self.flop = cards
                self.reset_street('flop')
            elif line.startswith('T '):
                self.turn = tok[1]
                self.reset_street('turn')
            elif line.startswith('R '):
                self.river = tok[1]
                self.reset_street('river')
            elif line.startswith('SHOW '):
                # SHOW <pos> <c1> <c2> [hand_desc...]
                pos = tok[1]
                p = self.players[pos]
                cards = f"{tok[2]} {tok[3]}"
                desc = ' '.join(tok[4:]) if len(tok) > 4 else ''
                show_line = f"{p.name}: shows [{cards}]" + (f" ({desc})" if desc else "")
                self.action_lines[self.cur_street].append(show_line)
                p.shown = True
                p.shown_desc = desc
                if not p.hole: p.hole = cards
            elif line.startswith('WIN '):
                pos = tok[1]
                self.winner_pos = pos
            elif line.startswith('SPLIT '):
                # SPLIT pos1 pos2 [pos3 ...] — chop pot among listed players
                self.split_winners = tok[1:]
                self.winner_pos = tok[1]  # primary winner for legacy paths
            elif line.startswith('UNCALLED '):
                # explicit uncalled override (rare)
                pass
            elif ':' in line:
                # position-keyed action
                pos, rest = line.split(':', 1)
                pos = pos.strip(); rest = rest.strip()
                self._do_action(pos, rest)
            else:
                raise ValueError(f"unparseable: {line!r}")
            i += 1

    def _do_action(self, pos, action_str):
        p = self.players[pos]
        tok = action_str.split()
        verb = tok[0]
        p.last_active_street = self.cur_street
        if verb == 'fold':
            p.folded = True
            self.action_lines[self.cur_street].append(f"{p.name}: folds")
        elif verb == 'check':
            self.action_lines[self.cur_street].append(f"{p.name}: checks")
        elif verb == 'call':
            need = self.cur_bet - p.committed
            if need >= p.chips:
                # all-in call
                actual = p.chips
                p.committed += actual; p.in_pot += actual; p.chips = 0
                p.allin = True
                self.action_lines[self.cur_street].append(
                    f"{p.name}: calls {fmt(actual)} and is all-in")
            else:
                p.committed += need; p.in_pot += need; p.chips -= need
                self.action_lines[self.cur_street].append(f"{p.name}: calls {fmt(need)}")
        elif verb == 'limp':
            # only valid PF for SB completing
            need = self.meta['bb'] - p.committed
            p.committed += need; p.in_pot += need; p.chips -= need
            self.action_lines[self.cur_street].append(f"{p.name}: calls {fmt(need)}")
        elif verb == 'bet':
            amount = int(tok[1].replace(',',''))
            p.committed += amount; p.in_pot += amount; p.chips -= amount
            self.cur_bet = amount; self.last_agg_pos = pos
            allin_suffix = ' and is all-in' if p.chips == 0 else ''
            if p.chips == 0: p.allin = True
            self.action_lines[self.cur_street].append(
                f"{p.name}: bets {fmt(amount)}{allin_suffix}")
        elif verb == 'raise':
            target = int(tok[1].replace(',',''))
            delta = target - self.cur_bet
            extra = target - p.committed
            if extra >= p.chips:
                # all-in raise
                actual_extra = p.chips
                actual_target = p.committed + actual_extra
                actual_delta = actual_target - self.cur_bet
                p.committed = actual_target; p.in_pot += actual_extra; p.chips = 0
                p.allin = True
                self.cur_bet = actual_target; self.last_agg_pos = pos
                self.action_lines[self.cur_street].append(
                    f"{p.name}: raises {fmt(actual_delta)} to {fmt(actual_target)} and is all-in")
            else:
                p.committed = target; p.in_pot += extra; p.chips -= extra
                self.cur_bet = target; self.last_agg_pos = pos
                self.action_lines[self.cur_street].append(
                    f"{p.name}: raises {fmt(delta)} to {fmt(target)}")
        elif verb == 'shove':
            # all-in for remaining stack
            amount = p.chips
            if self.cur_bet == 0:
                # bet shove
                p.committed += amount; p.in_pot += amount; p.chips = 0; p.allin = True
                self.cur_bet = amount; self.last_agg_pos = pos
                self.action_lines[self.cur_street].append(
                    f"{p.name}: bets {fmt(amount)} and is all-in")
            else:
                # raise shove
                target = p.committed + amount
                delta = target - self.cur_bet
                p.committed = target; p.in_pot += amount; p.chips = 0; p.allin = True
                self.cur_bet = target; self.last_agg_pos = pos
                self.action_lines[self.cur_street].append(
                    f"{p.name}: raises {fmt(delta)} to {fmt(target)} and is all-in")
        elif verb == 'show':
            cards = f"{tok[1]} {tok[2]}"
            desc = ' '.join(tok[3:]) if len(tok) > 3 else ''
            line = f"{p.name}: shows [{cards}]" + (f" ({desc})" if desc else "")
            self.action_lines[self.cur_street].append(line)
            p.shown = True; p.shown_desc = desc
            if not p.hole: p.hole = cards
        else:
            raise ValueError(f"unknown verb: {verb}")

    def finalize(self):
        """Resolve uncalled bets and pot."""
        # Find last action; if last actor was a fold and prior was a bet/raise that
        # wasn't called, set uncalled.
        # Simpler: scan all four streets in reverse for the last raise that wasn't called.
        # Compute total pot from in_pot.
        total = sum(p.in_pot for p in self.players.values())
        # If the hand ended without showdown, we may need to refund the uncalled portion.
        # Detect: last aggressive action on any street where everyone after folds without calling.
        # We'll do a simpler approach: check each street's actions in reverse order across all streets.
        for street in ['river','turn','flop','pf']:
            acts = self.action_lines[street]
            if not acts: continue
            # walk from end
            for i in range(len(acts)-1, -1, -1):
                a = acts[i]
                if 'folds' in a: continue
                # last non-fold action
                # if it's a raise/bet, check if it was called
                if ('raises ' in a or 'bets ' in a) and 'and is all-in' not in a:
                    # was it called? Check subsequent actions on same street for "calls"
                    bettor_name = a.split(':')[0]
                    bet_amt = int(a.split(' to ')[-1].replace(',','')) if ' to ' in a else \
                              int(a.split('bets ')[1].replace(',',''))
                    # look at subsequent actions in same street + following streets
                    callers_total = 0
                    matched = False
                    # just check if anyone on this street called
                    for ja in acts[i+1:]:
                        if 'calls ' in ja:
                            matched = True; break
                        if 'raises ' in ja:
                            matched = True; break
                    if not matched:
                        # uncalled. Compute the uncalled amount.
                        # The last call (if any) before the bettor's action sets the matched amount.
                        bettor = next(p for p in self.players.values() if p.name == bettor_name)
                        # find max committed by anyone OTHER than bettor on this street
                        max_other = max((p.committed for p in self.players.values()
                                         if p.name != bettor_name and not p.folded), default=0)
                        uncalled = bettor.committed - max_other
                        if uncalled > 0:
                            self.uncalled_amt = uncalled
                            self.uncalled_pos = bettor.pos
                            # Refund: don't subtract from total, but we'll insert
                            # the "Uncalled bet returned" line after action.
                            # Adjust pot:
                            total -= uncalled
                            bettor.in_pot -= uncalled
                            bettor.chips += uncalled
                    break
                else:
                    break
            break  # only process the latest street with actions
        self.total_pot = total
        self._validate_structure()

    def _validate_structure(self):
        """Structural validation per intake conversation 2026-05-03.
        Raises ValueError with hand_id + specific issue if hand is malformed.
        Catches the bug class that landed in V1/V2 fixtures: dealt players
        missing preflop actions, players acting after folding, and SB/BB
        posted by the wrong seats.
        """
        hid = self.meta['hand_id']
        errors = []

        # Check 1: SB and BB posted by the correct positions per layout
        sb_player = self.players['SB']
        bb_player = self.players['BB']
        # The blind-post lines are emitted by post_blinds_antes() which uses
        # self.players['SB'] / ['BB'] directly, so this is structurally guaranteed
        # by the layout indexing — but assert it explicitly so any future
        # refactor that breaks the invariant fails loudly.
        layout_sb_seat = self.layout.index('SB') + 1
        layout_bb_seat = self.layout.index('BB') + 1
        if sb_player.seat != layout_sb_seat:
            errors.append(f"SB seat mismatch: layout expects seat {layout_sb_seat}, got {sb_player.seat}")
        if bb_player.seat != layout_bb_seat:
            errors.append(f"BB seat mismatch: layout expects seat {layout_bb_seat}, got {bb_player.seat}")

        # Check 2: Every dealt player has at least one preflop action
        # (SB/BB are exempt — they "act" via blind post; if they didn't
        # take a non-blind action they're treated as folded by walkover.)
        # Actually we DO require them to have an explicit preflop action
        # if they're still in the hand at flop — handled by check 3.
        # Here: every non-blind position must have a preflop action line.
        pf_lines = self.action_lines['pf']
        actors_pf = set()
        for line in pf_lines:
            actor_name = line.split(':')[0]
            for p in self.players.values():
                if p.name == actor_name:
                    actors_pf.add(p.pos); break
        for pos in self.layout:
            if pos in ('SB', 'BB'): continue  # blinds exempt — see above
            if pos not in actors_pf:
                errors.append(f"position {pos} dealt cards but never acts preflop")

        # Check 3: No player acts after folding (any street)
        for street in ('pf', 'flop', 'turn', 'river'):
            folded = set()
            for line in self.action_lines[street]:
                actor_name = line.split(':')[0]
                actor_pos = next((p.pos for p in self.players.values()
                                  if p.name == actor_name), None)
                if actor_pos is None: continue
                if actor_pos in folded:
                    errors.append(f"{actor_pos} acts after folding on {street}: '{line.strip()}'")
                if 'folds' in line:
                    folded.add(actor_pos)

        if errors:
            joined = '; '.join(errors)
            raise ValueError(f"Hand {hid} structural validation failed: {joined}")

    def render(self):
        m = self.meta
        L = []
        ante_part = f"({fmt(m['ante'])})" if m['ante'] >= 0 else ""
        L.append(
            f"Poker Hand #{m['hand_id']}: Tournament #{m['tourney_id']}, "
            f"{m['buyin']} Hold'em No Limit - "
            f"Level{m['level']}({fmt(m['sb'])}/{fmt(m['bb'])}{ante_part}) - "
            f"{m['dt']}"
        )
        L.append(f"Table '{m['table']}' {m['n']}-max Seat #{self.btn_seat} is the button")
        for pos in self.layout:
            p = self.players[pos]
            L.append(f"Seat {p.seat}: {p.name} ({fmt(p.start_chips)} in chips)")
        if m['ante'] > 0:
            for pos in self.layout:
                p = self.players[pos]
                L.append(f"{p.name}: posts the ante {fmt(m['ante'])}")
        sb_p = self.players['SB']; bb_p = self.players['BB']
        L.append(f"{sb_p.name}: posts small blind {fmt(m['sb'])}")
        L.append(f"{bb_p.name}: posts big blind {fmt(m['bb'])}")
        L.append("*** HOLE CARDS ***")
        for pos in self.layout:
            p = self.players[pos]
            if p.name == self.players[self._hero_pos].name:
                L.append(f"Dealt to Hero [{p.hole}]")
            else:
                L.append(f"Dealt to {p.name} ")
        # PF actions
        for a in self.action_lines['pf']:
            L.append(a)
        # Flop
        if self.flop:
            L.append(f"*** FLOP *** [{self.flop}]")
            for a in self.action_lines['flop']:
                L.append(a)
        if self.turn:
            L.append(f"*** TURN *** [{self.flop}] [{self.turn}]")
            for a in self.action_lines['turn']:
                L.append(a)
        if self.river:
            L.append(f"*** RIVER *** [{self.flop} {self.turn}] [{self.river}]")
            for a in self.action_lines['river']:
                L.append(a)
        if self.uncalled_amt > 0:
            uname = self.players[self.uncalled_pos].name
            L.append(f"Uncalled bet ({fmt(self.uncalled_amt)}) returned to {uname}")
        L.append("*** SHOWDOWN ***")
        # Determine winner if not set explicitly
        if not self.winner_pos:
            survivors = [p for p in self.players.values() if not p.folded]
            if len(survivors) == 1:
                self.winner_pos = survivors[0].pos
        # Compute per-player winnings (chop-aware)
        if self.split_winners:
            share = self.total_pot // len(self.split_winners)
            winnings = {pos: share for pos in self.split_winners}
            # Distribute remainder to first listed winner
            remainder = self.total_pot - share * len(self.split_winners)
            if remainder:
                winnings[self.split_winners[0]] += remainder
        else:
            winnings = {self.winner_pos: self.total_pot}
        for pos, amt in winnings.items():
            p = self.players[pos]
            wname = 'Hero' if pos == self._hero_pos else p.name
            L.append(f"{wname} collected {fmt(amt)} from pot")
        # Summary
        L.append("*** SUMMARY ***")
        L.append(f"Total pot {fmt(self.total_pot)} | Rake 0 | Jackpot 0 | Bingo 0 | Fortune 0 | Tax 0")
        if self.flop:
            board = self.flop
            if self.turn: board += ' ' + self.turn
            if self.river: board += ' ' + self.river
            L.append(f"Board [{board}]")
        for pos in self.layout:
            p = self.players[pos]
            pname = 'Hero' if pos == self._hero_pos else p.name
            pos_label = ''
            if pos == 'BU': pos_label = ' (button)'
            elif pos == 'SB': pos_label = ' (small blind)'
            elif pos == 'BB': pos_label = ' (big blind)'
            if pos in winnings:
                amt = winnings[pos]
                if p.shown:
                    L.append(f"Seat {p.seat}: {pname}{pos_label} showed [{p.hole}] and won ({fmt(amt)}) with {p.shown_desc}")
                else:
                    L.append(f"Seat {p.seat}: {pname}{pos_label} collected ({fmt(amt)})")
            elif p.folded:
                # Hero's mucked cards are always shown in GG summary format
                hero_tag = f" [{p.hole}]" if pname == 'Hero' and p.hole else ''
                # Determine when folded
                if p.last_active_street == 'pf':
                    if p.in_pot <= m['ante']:  # only ante (or even nothing)
                        L.append(f"Seat {p.seat}: {pname}{pos_label} folded before Flop (didn't bet){hero_tag}")
                    else:
                        L.append(f"Seat {p.seat}: {pname}{pos_label} folded before Flop{hero_tag}")
                elif p.last_active_street == 'flop':
                    L.append(f"Seat {p.seat}: {pname}{pos_label} folded on the Flop{hero_tag}")
                elif p.last_active_street == 'turn':
                    L.append(f"Seat {p.seat}: {pname}{pos_label} folded on the Turn{hero_tag}")
                elif p.last_active_street == 'river':
                    L.append(f"Seat {p.seat}: {pname}{pos_label} folded on the River{hero_tag}")
                else:
                    L.append(f"Seat {p.seat}: {pname}{pos_label} folded before Flop (didn't bet){hero_tag}")
            else:
                # didn't fold, didn't win — must have shown and lost
                if p.shown:
                    L.append(f"Seat {p.seat}: {pname}{pos_label} showed [{p.hole}] and lost with {p.shown_desc}")
                else:
                    # Edge case: hand ended without explicit fold (e.g., hero mucked)
                    L.append(f"Seat {p.seat}: {pname}{pos_label} mucked")
        return '\n'.join(L) + '\n\n\n'


def build_hand(spec):
    """spec is a dict with all the metadata + 'actions' (list of DSL strings)."""
    h = Hand(spec['hand_id'], spec['tourney_id'], spec['buyin'],
             spec['level'], spec['sb'], spec['bb'], spec['ante'],
             spec['dt'], spec['table'], spec['n'], spec['btn'],
             spec['day_id'])
    # Add Hero
    hero_pos, hero_chips, hero_hole = spec['hero']
    h.add_player(hero_pos, hero_chips, hole=hero_hole, name='Hero')
    h._hero_pos = hero_pos
    # Default villain stack
    default = spec.get('villain_default_chips', hero_chips)
    custom = spec.get('villains', {})
    h.fill_villains(hero_pos, hero_chips, default, custom)
    h.post_blinds_antes()
    h.execute(spec['actions'])
    h.finalize()
    return h.render()
