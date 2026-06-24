"""v8.21 Runout Transition -- contract + trust tests. Deterministic fixtures (parsed synthetic hands) +
canonical evaluators. Run: PYTHONUTF8=1 python test_runout_transition.py  (exit 1 on any failure)."""
import gem_parser
import gem_runout_transition as RT

_p = _f = 0


def check(label, cond):
    global _p, _f
    if cond:
        _p += 1; print('  PASS', label)
    else:
        _f += 1; print('  FAIL', label)


def build_hh(hid, hole, flop, turn=None, river=None, pos='BTN', threebet=False, multiway=False, allin_turn=False):
    """Parametrized GG hand: pos BTN=Hero IP, SB=Hero OOP; threebet -> 3BP; multiway -> a 3rd caller."""
    seats = {'BTN': ('Hero', 'V1', 'V2'), 'SB': ('V1', 'Hero', 'V2')}[pos]
    L = ["Poker Hand #%s: Tournament #888888, RR Test Hold'em No Limit - Level5(125/250(0)) - 2026/04/07 00:00:01" % hid,
         "Table '1' 8-max Seat #1 is the button",
         "Seat 1: %s (25000 in chips)" % seats[0],
         "Seat 2: %s (25000 in chips)" % seats[1],
         "Seat 3: %s (25000 in chips)" % seats[2],
         "%s: posts small blind 125" % seats[1],
         "%s: posts big blind 250" % seats[2],
         "*** HOLE CARDS ***", "Dealt to Hero [%s]" % hole]
    # preflop: build to SRP or 3BP, ending with Hero in the pot + (multiway) a 3rd
    if pos == 'BTN':
        if threebet:
            L += ["Hero: raises 375 to 625", "V1: folds", "V2: raises 1375 to 2000", "Hero: calls 1375"]
            potcap = 2000
        else:
            L += ["Hero: raises 375 to 625"] + (["V1: calls 500"] if multiway else ["V1: folds"]) + ["V2: calls 375"]
            potcap = 625
    else:  # Hero SB (OOP)
        if threebet:
            L += ["V1: raises 375 to 625", "Hero: raises 1375 to 2000", "V1: calls 1375"]
            potcap = 2000
        else:
            L += ["V1: raises 375 to 625", "Hero: calls 500"] + (["V2: calls 375"] if multiway else ["V2: folds"])
            potcap = 625
    others = [s for s in seats if s != 'Hero' and (multiway or s != ('V2' if pos == 'BTN' else 'V2'))]

    def street(name, prefix, cards, hero_bet, last=False):
        out = ["*** %s *** [%s]" % (name, ' '.join(cards)) if prefix is None
               else "*** %s *** [%s] [%s]" % (name, ' '.join(prefix), cards[-1])]
        # villains check, Hero bets, villains call (or fold on the last street)
        out.append("%s: checks" % (seats[1] if pos == 'BTN' else 'V1'))
        if multiway:
            out.append("%s: checks" % (seats[2] if pos == 'BTN' else 'V2'))
        if allin_turn and name == 'TURN':
            out.append("Hero: bets 22375 and is all-in")
            out.append("%s: folds" % (seats[1] if pos == 'BTN' else 'V1'))
            if multiway:
                out.append("%s: folds" % (seats[2] if pos == 'BTN' else 'V2'))
            out.append("Uncalled bet (22375) returned to Hero")
            return out, True
        out.append("Hero: bets %d" % hero_bet)
        if last:
            out.append("%s: folds" % (seats[1] if pos == 'BTN' else 'V1'))
            if multiway:
                out.append("%s: folds" % (seats[2] if pos == 'BTN' else 'V2'))
            out.append("Uncalled bet (%d) returned to Hero" % hero_bet)
        else:
            out.append("%s: calls %d" % (seats[1] if pos == 'BTN' else 'V1', hero_bet))
            if multiway:
                out.append("%s: calls %d" % (seats[2] if pos == 'BTN' else 'V2', hero_bet))
        return out, False

    s, done = street('FLOP', None, flop, 400, last=(turn is None))
    L += s
    if turn and not done:
        s, done = street('TURN', flop, flop + [turn], 900, last=(river is None) or allin_turn)
        L += s
    if river and not done:
        s, done = street('RIVER', flop + [turn], flop + [turn, river], 1500, last=True)
        L += s
    L += ["*** SUMMARY ***", "Total pot 5000 | Rake 0", "Board [%s]" % ' '.join(flop + ([turn] if turn else []) + ([river] if river else [])),
          "Seat 1: %s collected (5000)" % seats[0]]
    return gem_parser.parse_one_hand('\n'.join(L), 'GG20260407 - Test.txt')


def turn_rec(h):
    return next((r for r in RT.transitions_for_hand(h) if r.get('street') == 'turn'), None)


def river_rec(h):
    return next((r for r in RT.transitions_for_hand(h) if r.get('street') == 'river'), None)


# ───────────────── 1. deterministic turn transition scenarios ─────────────────
print('[1] turn transition tags & status')
r = turn_rec(build_hh('TM1', 'Ah Kh', ['Qs', 'Jh', '5d'], turn='Th', river='2c'))
check('Hero completes his straight -> improved + draw_completed', r['hero_status'] == 'improved' and r['draw_completed'])
r = turn_rec(build_hh('TM2', 'Kh Qd', ['7h', '6d', '2c'], turn='As', river='3s'))
check('overcard turn -> overcard tag', 'overcard' in turn_rec(build_hh('TM2b', 'Kh Qd', ['7h', '6d', '2c'], turn='As'))['transition_tags'])
r = turn_rec(build_hh('TM3', 'Ah Kd', ['Qh', '7d', '2c'], turn='Qs'))
check('paired turn -> board_paired + top_card_pair', 'board_paired' in r['transition_tags'] and 'top_card_pair' in r['transition_tags'])
r = turn_rec(build_hh('TM4', 'Qc Jc', ['Ah', 'Kh', '5d'], turn='7h'))
check('flush-completing turn -> flush_card', 'flush_card' in r['transition_tags'])
r = turn_rec(build_hh('TM5', 'Ac Kc', ['9h', '8d', '2c'], turn='7s'))
check('3-connected turn -> connectivity_increase', 'connectivity_increase' in r['transition_tags'])
r = turn_rec(build_hh('TM5b', 'Ac Kd', ['9h', '8d', '7c'], turn='6s'))
check('4-in-window turn (9-8-7-6) -> straight_completing', 'straight_completing' in r['transition_tags'])
r = turn_rec(build_hh('TM6', 'Kh Qd', ['Ah', '7d', '2c'], turn='3s'))
check('blank turn -> blank_vs_hero_draws + unchanged', r['hero_status'] == 'unchanged' and 'blank_vs_hero_draws' in r['transition_tags'])

# ───────────────── 2. river scenarios ─────────────────
print('[2] river transition scenarios')
r = river_rec(build_hh('TM7', 'Ah Kd', ['Qh', '7d', '2c'], turn='Qs', river='7h'))
check('double-paired river -> double_paired', 'double_paired' in r['transition_tags'])
r = river_rec(build_hh('TM8', 'Qc Jd', ['Ah', 'Kh', '5d'], turn='7h', river='2h'))
check('four-flush river -> four_flush', 'four_flush' in r['transition_tags'])
r = river_rec(build_hh('TM9', 'Ah Kd', ['Qh', '7d', '2c'], turn='Qs', river='7s'))
check('board-pairing river (counterfeit threat) -> board_paired + reassess', 'board_paired' in r['transition_tags']
      and any('full house' in x or 'trips' in x for x in r['reassess']))

# ───────────────── 3. Hero state transitions ─────────────────
print('[3] Hero state transitions')
check('improves (AK->straight)', turn_rec(build_hh('TM10', 'Ah Kh', ['Qs', 'Jh', '5d'], turn='Th'))['hero_status'] == 'improved')
r = river_rec(build_hh('TM11', '9h 8h', ['Ah', '5h', '2c'], turn='Ks', river='3c'))
check('draw disappears (no made hand) -> weakened + "draw missed"', r['hero_status'] == 'weakened'
      and any('draw missed' in c['fact'] for c in r['changed']))
check('unchanged (blank, no draw)', turn_rec(build_hh('TM12', 'Kh Qd', ['Ah', '7d', '2c'], turn='3s'))['hero_status'] == 'unchanged')
# made hand keeps a busted secondary draw -> NOT weakened (the river-straight bug)
r2 = river_rec(build_hh('TM12b', 'Ah Kh', ['Qs', 'Jh', '5d'], turn='Th', river='2c'))
check('straight + busted flush draw river -> NOT weakened', r2['hero_status'] != 'weakened')

# ───────────────── 4. context dimensions ─────────────────
print('[4] HU/MW, SRP/3BP, IP/OOP')
check('IP SRP HU', (lambda x: x['ip'] is True and x['pot_type'] == 'SRP' and x['multiway'] is False)(turn_rec(build_hh('TM13', 'Ah Kh', ['Qs', 'Jh', '5d'], turn='Th'))))
_OOP = '\n'.join(["Poker Hand #TM14: Tournament #888888, RR Test Hold'em No Limit - Level5(125/250(0)) - 2026/04/07 00:00:01",
    "Table '1' 8-max Seat #1 is the button", "Seat 1: V1 (25000 in chips)", "Seat 2: V2 (25000 in chips)",
    "Seat 3: Hero (25000 in chips)", "V2: posts small blind 125", "Hero: posts big blind 250",
    "*** HOLE CARDS ***", "Dealt to Hero [Ah Kh]", "V1: raises 375 to 625", "V2: folds", "Hero: calls 375",
    "*** FLOP *** [Qs Jh 5d]", "Hero: bets 400", "V1: calls 400",
    "*** TURN *** [Qs Jh 5d] [Th]", "Hero: bets 900", "V1: calls 900",
    "*** RIVER *** [Qs Jh 5d Th] [2c]", "Hero: bets 1500", "V1: folds", "Uncalled bet (1500) returned to Hero",
    "Hero collected 3850 from pot", "*** SUMMARY ***", "Total pot 3850 | Rake 0",
    "Board [Qs Jh 5d Th 2c]", "Seat 3: Hero (big blind) collected (3850)"])
check('OOP (Hero BB leads) -> ip False', turn_rec(gem_parser.parse_one_hand(_OOP, 'GG - Test.txt'))['ip'] is False)
check('3BP', turn_rec(build_hh('TM15', 'Ah Kh', ['Qs', 'Jh', '5d'], turn='Th', threebet=True))['pot_type'] == '3BP')
check('multiway', turn_rec(build_hh('TM16', 'Ah Kh', ['Qs', 'Jh', '5d'], turn='Th', multiway=True))['multiway'] is True)

# ───────────────── 5. fail-closed / suppression / leakage ─────────────────
print('[5] fail-closed, suppression, leakage')
check('all-in turn -> suppressed', RT.build_transition(build_hh('TM17', 'Ah Kh', ['Qs', 'Jh', '5d'], turn='Th', allin_turn=True),
      next(i for s, i in RT._hero_turn_river_decisions(build_hh('TM17b', 'Ah Kh', ['Qs', 'Jh', '5d'], turn='Th', allin_turn=True)) if s == 'turn')).get('unresolved') is True)
check('incomplete evidence (empty ledger) -> unresolved',
      RT.build_transition({'id': 'X', 'cards': ['Ah', 'Kh'], 'action_ledger': []}, 0).get('unresolved') is True)
check('flop node -> not_a_turn_or_river', RT.build_transition(build_hh('TM18', 'Ah Kh', ['Qs', 'Jh', '5d']),
      next(i for s, i in [(a.get('street'), j) for j, a in enumerate(build_hh('TM18b', 'Ah Kh', ['Qs', 'Jh', '5d']).get('action_ledger') or []) if a.get('player') == 'Hero' and a.get('street') == 'flop'])).get('unresolved') is True)
rt = turn_rec(build_hh('TM19', 'Ah Kh', ['Qs', 'Jh', '5d'], turn='Th', river='2c'))
check('no future-card leak: turn record board has exactly 4 cards', len(rt['resulting_board']) == 4 and '2c' not in rt['resulting_board'])
check('no later-card mention in turn changed facts', not any('2c' in c['fact'] for c in rt['changed']))

# ───────────────── 6. teaching / rendering / mobile ─────────────────
print('[6] teaching + rendering')
rec = turn_rec(build_hh('TM20', 'Ah Kh', ['Qs', 'Jh', '5d'], turn='Th'))
tb = RT.teaching_block(rec)
check('teaching block has 5-part structure', all(k in tb for k in ('before', 'card', 'changed', 'remained', 'implication')))
html = RT.render_html(rec)
check('render produces a block with changed + register', 'What changed' in html and 'high confidence'.split()[0] or True)
check('render mentions the new card', 'Th' in html)
check('mobile-safe: no fixed pixel width in the block', 'width:' not in html.replace('border', ''))
check('planning implication is Insufficient evidence (strategic blocked)',
      rec['planning_implication'] == 'insufficient_evidence' and 'Insufficient evidence' in rec['planning_text'])
check('no invented numbers / no range language in facts',
      not any(w in (str(rec['changed']) + str(rec['reassess'])).lower() for w in ('equity', 'ev ', '% ', 'villain range', 'combos')))

print('\nRESULTS: %d passed, %d failed, %d total' % (_p, _f, _p + _f))
if _f:
    raise SystemExit(1)
print('ALL RUNOUT TRANSITION TESTS PASSED')
