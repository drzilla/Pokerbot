#!/usr/bin/env python3
"""
gem_opponent_profiler.py — Per-villain behavioral profiling (4-dimensional).

Classifies each opponent along 4 axes from observable session actions:
  1. Range width:    tight ↔ loose       (VPIP %)
  2. Aggression:     passive ↔ aggressive (PFR/VPIP, postflop AF)
  3. Stickiness:     non-sticky ↔ sticky  (fold-to-cbet, WTSD tendency)
  4. Competence:     bad ↔ good           (limp frequency, min-bet, sizing tells)

Then maps the 4D profile to one of 10 named archetypes:
  Nit/Rock, Calling Station, Fish, Whale, Maniac, LAG Reg, TAG Reg,
  Solid Reg, Danger Reg, Fun Rec / Gambler.

Each archetype carries an exploit prescription so the analyst and renderer
can surface "you bluffed a calling station on the river — stop doing that."
"""
from collections import defaultdict


# ============================================================
# ARCHETYPE DEFINITIONS — the 10 archetypes with their 4D profiles
# ============================================================

ARCHETYPES = {
    'NIT': {
        'emoji': '🪨', 'label': 'Nit / Rock',
        'dimensions': 'Tight · Low-medium aggression · Non-sticky · Medium competence',
        'tells': 'Enters rarely (<20% VPIP); folds too much postflop; '
                 'when they raise big, believe them',
        'exploit': 'Steal blinds freely; bluff small pots; fold when they '
                   'show strength — their raises are always value',
    },
    'CALLING_STATION': {
        'emoji': '📞', 'label': 'Calling Station',
        'dimensions': 'Loose · Passive · Very sticky · Low competence',
        'tells': 'High VPIP (>35%), low PFR; calls too much on every street; '
                 'rarely raises; will not fold middle pair',
        'exploit': 'Value-bet thinly on every street; stop bluffing entirely; '
                   'your job is boring — bet good hands, check bad ones',
    },
    'FISH': {
        'emoji': '🐟', 'label': 'Fish',
        'dimensions': 'Loose/random · Usually passive · Sticky-ish · Low competence',
        'tells': 'Wide random range; limps often; calls too much pre and post; '
                 'sizing is erratic (min-bets, overbets randomly)',
        'exploit': 'Value-bet; isolate; simplify — don\'t get fancy, just '
                   'play straightforward and let them pay you off',
    },
    'WHALE': {
        'emoji': '🐋', 'label': 'Whale',
        'dimensions': 'Very loose · Random · Very sticky · Very low competence',
        'tells': 'Plays almost every hand; calls any bet; makes huge mistakes; '
                 'will put in stacks with third pair; expects nonsense',
        'exploit': 'Play huge pots for value; don\'t bluff at all; expect '
                   'nonsensical plays — they\'ll pay off your value forever',
    },
    'MANIAC': {
        'emoji': '🔥', 'label': 'Maniac',
        'dimensions': 'Very loose · Very aggressive · Sticky-aggressive · Low-medium competence',
        'tells': 'Extremely high VPIP (>45%) + high AF (>3); bets/raises '
                 'too much; doesn\'t like folding; attacks relentlessly',
        'exploit': 'Trap with strong hands; widen value call-downs; '
                   'don\'t ego-war bluff — let them hang themselves',
    },
    'LAG': {
        'emoji': '⚡', 'label': 'LAG Reg',
        'dimensions': 'Loose · Aggressive · Selectively sticky · High competence',
        'tells': 'Moderate-high VPIP (28-40%) + high PFR; applies pressure '
                 'with logic; can fold when beaten; well-timed aggression',
        'exploit': '3-bet/4-bet correctly for value; call down more vs their '
                   'barrels; don\'t overfold — but respect their biggest bets',
    },
    'TAG': {
        'emoji': '🎖️', 'label': 'TAG Reg',
        'dimensions': 'Tight-ish · Aggressive · Disciplined · Medium-high competence',
        'tells': 'VPIP 18-25%, high PFR; solid default strategy; doesn\'t '
                 'spew; respects position; consistent sizing',
        'exploit': 'Respect big aggression; attack their capped checking ranges; '
                   'steal in position but fold to their 3-bets OOP',
    },
    'SOLID_REG': {
        'emoji': '📊', 'label': 'Solid Reg',
        'dimensions': 'Balanced · Controlled · Disciplined · High competence',
        'tells': 'Near-GTO frequencies; hard to exploit; adapts within session; '
                 'doesn\'t give away free information',
        'exploit': 'Avoid marginal wars; find small population exploits; '
                   'don\'t autopilot — they\'re watching you too',
    },
    'DANGER_REG': {
        'emoji': '☠️', 'label': 'Danger Reg',
        'dimensions': 'Adaptive · Aggressive · Disciplined · Very high competence',
        'tells': 'Adjusts to your tendencies; varied bet sizing; exploits your '
                 'leaks in real time; uncomfortable to play against',
        'exploit': 'Seat-select away when possible; don\'t autopilot; mix up '
                   'your own lines — they\'re the ones exploiting YOU',
    },
    'FUN_REC': {
        'emoji': '🎰', 'label': 'Fun Rec / Gambler',
        'dimensions': 'Loose · Medium-high aggression · Sticky · Low competence',
        'tells': 'Plays for action; limps then calls raises; occasional wild '
                 'bluffs; sizing tells (min-bets value, overbets bluffs)',
        'exploit': 'Let them punt; go heavy on value; avoid fancy bluffs — '
                   'they call too much but occasionally surprise you',
    },
}


# ============================================================
# PROFILER — aggregate per-villain stats from session hands
# ============================================================

def profile_opponents(hands, hero_name='Hero'):
    """Build per-villain behavioral stats from the session's hands.

    Returns {villain_key: profile_dict} where villain_key is
    "tournament_id|player_hash" — same convention as gem_villain_intel.py.

    BUG-B fix (v8.8.1): re-keyed from tournament|position to per-player
    identity, fixed VPIP to count calls/limps (not just opens), fixed
    denominator to count only hands where the specific player was present,
    and uses hand['villains'] instead of stacks_behind to cover all
    non-Hero players without position-sampling bias.
    """
    villains = defaultdict(lambda: {
        'hands_seen': 0,
        'vpip': 0,           # voluntarily put money in (called or raised pre)
        'pfr': 0,            # preflop raise
        'limp': 0,           # preflop limp (call, no raise)
        'postflop_bets': 0,
        'postflop_raises': 0,
        'postflop_calls': 0,
        'postflop_checks': 0,
        'postflop_folds': 0,
        'went_to_sd': 0,
        'min_bets': 0,       # competence signal: min-bet sizing
        'example_hand_ids': [],      # hands showing characteristic behavior
        'evidence_descriptions': [],  # what the villain did in each example
        'positions_seen': set(),
        'tournament': '',
    })

    # Resolve hero name: parser stores "Hero", analyzer passes real name
    def _resolve_hero(h):
        return h.get('hero', '') or hero_name

    for h in hands:
        if not isinstance(h, dict):
            continue
        tid = h.get('tournament_id') or ''
        if not tid:
            continue
        hid = h.get('id', '')
        _hero = _resolve_hero(h)
        v_dict = h.get('villains') or {}

        # Build player→position map and position→player map for this hand
        _player_to_pos = {}
        for vname, vinfo in v_dict.items():
            _player_to_pos[vname] = vinfo.get('position', '?')

        # Track each villain in this hand (using villains dict, not stacks_behind)
        for vname, vinfo in v_dict.items():
            if vname == _hero:
                continue
            vkey = f"{tid}|{vname}"
            v = villains[vkey]
            v['hands_seen'] += 1
            v['positions_seen'].add(vinfo.get('position', '?'))
            v['tournament'] = tid

        # Use action_ledger to count VPIP, PFR, limp per villain
        ledger = h.get('action_ledger') or []
        _pf_raisers = set()   # players who raised preflop
        _pf_callers = set()   # players who called preflop (voluntary)
        for entry in ledger:
            if entry.get('street') != 'preflop':
                continue
            player = entry.get('player', '')
            action = entry.get('action', '')
            if player == _hero or player not in v_dict:
                continue
            if action == 'raises':
                _pf_raisers.add(player)
            elif action == 'calls':
                _pf_callers.add(player)

        # VPIP = player voluntarily put money in (raised OR called).
        # Each player counts at most once per hand for VPIP.
        _pf_voluntary = _pf_raisers | _pf_callers
        for player in _pf_voluntary:
            vkey = f"{tid}|{player}"
            villains[vkey]['vpip'] += 1
        for player in _pf_raisers:
            vkey = f"{tid}|{player}"
            villains[vkey]['pfr'] += 1
        # Caller who never raised = limp or cold-call
        for player in (_pf_callers - _pf_raisers):
            vkey = f"{tid}|{player}"
            villains[vkey]['limp'] += 1

        # Postflop actions from ledger (bets, raises, calls, checks, folds)
        for entry in ledger:
            if entry.get('street') == 'preflop':
                continue
            player = entry.get('player', '')
            action = entry.get('action', '')
            if player == _hero or player not in v_dict:
                continue
            vkey = f"{tid}|{player}"
            if action == 'bets':
                villains[vkey]['postflop_bets'] += 1
            elif action == 'raises':
                villains[vkey]['postflop_raises'] += 1
            elif action == 'calls':
                villains[vkey]['postflop_calls'] += 1
            elif action == 'checks':
                villains[vkey]['postflop_checks'] += 1
            elif action == 'folds':
                villains[vkey]['postflop_folds'] += 1

        # Showdown — only credit villains who were actually in the hand
        if h.get('went_to_sd'):
            for vname in v_dict:
                if vname == _hero:
                    continue
                vkey = f"{tid}|{vname}"
                villains[vkey]['went_to_sd'] += 1

    # Classify each villain along 4 dimensions
    # B-V10: minimum 15 hands to classify (was 5 — too low, produced
    # false Nit tags on players who just got junk for 10 hands).
    # Also require at least 1 showdown for medium+ confidence.
    _MIN_HANDS_TO_CLASSIFY = 15
    _MIN_SD_FOR_CONFIDENCE = 1

    result = {}
    for vkey, v in villains.items():
        n = v['hands_seen']
        if n < _MIN_HANDS_TO_CLASSIFY:
            v['archetype'] = 'UNKNOWN'
            v['confidence'] = 'low'
            v['reason'] = f'Only {n} hands (need {_MIN_HANDS_TO_CLASSIFY}) — not enough to classify'
            v['dimensions'] = {}
            result[vkey] = v
            continue

        # Dimension 1: Range width (VPIP %)
        vpip_pct = (v['vpip'] / n * 100) if n else 0
        if vpip_pct > 50:
            range_width = 'very_loose'
        elif vpip_pct > 35:
            range_width = 'loose'
        elif vpip_pct > 25:
            range_width = 'moderate'
        elif vpip_pct > 18:
            range_width = 'tight_ish'
        else:
            range_width = 'tight'

        # Dimension 2: Aggression (PFR/VPIP + postflop AF)
        pfr_pct = (v['pfr'] / n * 100) if n else 0
        pfr_vpip = (v['pfr'] / max(v['vpip'], 1)) if v['vpip'] else 0
        post_agg = v['postflop_bets'] + v['postflop_raises']
        post_pass = max(v['postflop_calls'], 1)
        af = post_agg / post_pass if post_pass else 1.0
        if pfr_pct > 25 or af > 3.0:
            aggression = 'very_aggressive'
        elif pfr_pct > 18 or af > 2.0:
            aggression = 'aggressive'
        elif pfr_pct > 10:
            aggression = 'moderate'
        else:
            aggression = 'passive'

        # Dimension 3: Stickiness (fold frequency postflop)
        post_total = (v['postflop_folds'] + v['postflop_calls'] +
                      v['postflop_bets'] + v['postflop_raises'])
        fold_pct = (v['postflop_folds'] / max(post_total, 1) * 100) if post_total else 50
        sd_pct = (v['went_to_sd'] / max(n, 1) * 100) if n else 0
        if fold_pct < 20 or sd_pct > 35:
            stickiness = 'very_sticky'
        elif fold_pct < 35 or sd_pct > 25:
            stickiness = 'sticky'
        elif fold_pct > 60:
            stickiness = 'non_sticky'
        else:
            stickiness = 'moderate'

        # Dimension 4: Competence (limp frequency, sizing tells)
        limp_pct = (v['limp'] / max(v['vpip'], 1) * 100) if v['vpip'] else 0
        if limp_pct > 40 or v['min_bets'] > n * 0.1:
            competence = 'low'
        elif pfr_vpip > 0.6 and fold_pct > 30:
            competence = 'high'
        elif pfr_vpip > 0.5:
            competence = 'medium_high'
        else:
            competence = 'medium'

        v['vpip_pct'] = round(vpip_pct, 1)
        v['pfr_pct'] = round(pfr_pct, 1)
        v['af'] = round(af, 1)
        v['sd_pct'] = round(sd_pct, 1)
        v['dimensions'] = {
            'range_width': range_width,
            'aggression': aggression,
            'stickiness': stickiness,
            'competence': competence,
        }

        # Map 4D → archetype
        arch = _classify_archetype(range_width, aggression, stickiness, competence)
        v['archetype'] = arch
        # B-V10: require showdowns for confidence; raise thresholds
        _has_sd = v['went_to_sd'] >= _MIN_SD_FOR_CONFIDENCE
        if n >= 30 and _has_sd:
            v['confidence'] = 'high'
        elif n >= 20 and _has_sd:
            v['confidence'] = 'medium'
        else:
            v['confidence'] = 'low'
        meta = ARCHETYPES.get(arch, {})
        v['reason'] = (f"VPIP {vpip_pct:.0f}% · PFR {pfr_pct:.0f}% · AF {af:.1f} · "
                       f"SD {sd_pct:.0f}% → {meta.get('dimensions', '')}")
        result[vkey] = v

    # Second pass: collect BEHAVIORAL EVIDENCE hands per villain.
    # Now that we know each villain's archetype, find hands where
    # the villain demonstrated characteristic behavior.
    for h in hands:
        if not isinstance(h, dict):
            continue
        tid = h.get('tournament_id') or ''
        if not tid:
            continue
        hid = h.get('id', '')
        v_dict = h.get('villains') or {}
        opener = h.get('opener_position', '')
        # Map opener position label → player name for this hand
        _opener_player = None
        for vname, vinfo in v_dict.items():
            if vinfo.get('position') == opener:
                _opener_player = vname
                break

        for vname, vinfo in v_dict.items():
            vkey = f"{tid}|{vname}"
            v = result.get(vkey)
            if not v or v.get('archetype') in ('UNKNOWN', None):
                continue
            if len(v['example_hand_ids']) >= 10:
                continue
            arch = v['archetype']
            evidence = None
            _is_opener = (vname == _opener_player)

            # Station/Fish/Whale: villain called Hero's bet (sticky behavior)
            if arch in ('CALLING_STATION', 'FISH', 'WHALE'):
                if h.get('went_to_sd') and not _is_opener:
                    evidence = 'called down to showdown'
                elif _is_opener and not h.get('hero_3bet'):
                    evidence = 'opened/limped and called'

            # Nit: villain folded to Hero's aggression
            elif arch == 'NIT':
                if not h.get('went_to_sd') and _is_opener:
                    evidence = 'opened then folded to pressure'

            # Maniac/LAG: villain raised or re-raised
            elif arch in ('MANIAC', 'LAG', 'FUN_REC'):
                if h.get('villain_xr_flop') or h.get('villain_xr_turn'):
                    evidence = 'check-raised postflop'
                elif _is_opener and h.get('pf_raise_count', 0) >= 2:
                    evidence = 'opened aggressively'

            # TAG/Solid/Danger: villain showed disciplined aggression
            elif arch in ('TAG', 'SOLID_REG', 'DANGER_REG'):
                if h.get('went_to_sd') and _is_opener:
                    evidence = 'value-bet to showdown'

            if evidence:
                v['example_hand_ids'].append(hid)
                v['evidence_descriptions'].append(evidence)

    return result


def _classify_archetype(range_width, aggression, stickiness, competence):
    """Map the 4 dimensions to one of the 10 named archetypes."""

    # Very loose + very aggressive + bad = MANIAC
    if range_width in ('very_loose',) and aggression in ('very_aggressive',):
        return 'MANIAC'

    # Very loose + passive/random + very sticky + very low = WHALE
    if range_width == 'very_loose' and stickiness == 'very_sticky' and competence == 'low':
        return 'WHALE'

    # Loose + passive + very sticky + low = CALLING STATION
    if (range_width in ('loose', 'very_loose') and aggression == 'passive'
            and stickiness in ('sticky', 'very_sticky')):
        return 'CALLING_STATION'

    # Loose + passive/moderate + sticky + low = FISH
    if (range_width in ('loose', 'very_loose') and competence == 'low'
            and aggression in ('passive', 'moderate')):
        return 'FISH'

    # Loose + medium-high aggression + sticky + low = FUN REC
    if (range_width in ('loose', 'moderate') and competence == 'low'
            and aggression in ('moderate', 'aggressive') and stickiness in ('sticky',)):
        return 'FUN_REC'

    # Loose + aggressive + selectively sticky + high = LAG REG
    if (range_width in ('loose', 'moderate') and aggression in ('aggressive', 'very_aggressive')
            and competence in ('high', 'medium_high')):
        return 'LAG'

    # Tight + aggressive + disciplined + high = DANGER REG
    if (range_width in ('tight', 'tight_ish') and aggression in ('aggressive', 'very_aggressive')
            and competence == 'high' and stickiness in ('moderate', 'non_sticky')):
        return 'DANGER_REG'

    # Tight + aggressive + disciplined + medium-high = TAG
    if (range_width in ('tight', 'tight_ish') and aggression in ('aggressive', 'very_aggressive')
            and competence in ('medium_high', 'medium')):
        return 'TAG'

    # Moderate + controlled + disciplined + high = SOLID REG
    if competence in ('high', 'medium_high') and stickiness in ('moderate', 'non_sticky'):
        return 'SOLID_REG'

    # Tight + low-medium aggression + non-sticky = NIT
    if (range_width in ('tight', 'tight_ish') and aggression in ('passive', 'moderate')
            and stickiness in ('non_sticky', 'moderate')):
        return 'NIT'

    # Catch-all: moderate everything = TAG/REG
    if competence in ('medium', 'medium_high'):
        return 'TAG'
    return 'FISH'  # default for unclassifiable low-competence players


def tag_hands_with_archetypes(hands, profiles):
    """Tag each hand with the primary villain's archetype.

    Mutates hands in place: adds 'villain_archetype', 'villain_archetype_label',
    'villain_exploit_note', 'villain_example_hids'.
    """
    # Build a set of hand IDs seen so far, per villain key.
    # Only include PRIOR hands as evidence (can't tag based on future behavior).
    _seen_by_vkey = {}  # vkey → list of (hid, evidence_desc) in temporal order

    # First pass: build temporal evidence per villain from the evidence pass
    for vkey, profile in profiles.items():
        _eids = profile.get('example_hand_ids', [])
        _edescs = profile.get('evidence_descriptions', [])
        _seen_by_vkey[vkey] = list(zip(_eids, _edescs + [''] * len(_eids)))

    # Build hand-ID to index mapping for temporal ordering
    _hid_to_idx = {h.get('id', ''): i for i, h in enumerate(hands)
                   if isinstance(h, dict)}

    for h in hands:
        if not isinstance(h, dict):
            continue
        tid = h.get('tournament_id') or ''
        if not tid:
            continue
        opener_pos = h.get('opener_position', '')
        v_dict = h.get('villains') or {}
        # Find the opener's player name from the villains dict
        _opener_player = None
        _opener_rec = None
        for vname, vinfo in v_dict.items():
            if vinfo.get('position') == opener_pos:
                _opener_player = vname
                _opener_rec = vinfo
                break
        if not _opener_player:
            continue
        vkey = f"{tid}|{_opener_player}"
        profile = profiles.get(vkey)
        if profile and profile.get('archetype', 'UNKNOWN') != 'UNKNOWN':
            arch = profile['archetype']
            meta = ARCHETYPES.get(arch, {})
            h['primary_villain_hash'] = vkey
            h['villain_archetype'] = arch
            h['villain_archetype_label'] = f"{meta.get('emoji', '❓')} {meta.get('label', arch)}"
            h['villain_archetype_reason'] = profile.get('reason', '')
            h['villain_exploit_note'] = meta.get('exploit', '')
            h['villain_archetype_confidence'] = profile.get('confidence', 'low')
            # Only include example hands that came BEFORE this hand
            _current_idx = _hid_to_idx.get(h.get('id', ''), 999999)
            _prior_examples = [eid for eid, _ in _seen_by_vkey.get(vkey, [])
                               if _hid_to_idx.get(eid, 999999) < _current_idx]
            h['villain_example_hids'] = _prior_examples[:10]
            # SPEC #0: write archetype data into the unified villains record
            if _opener_rec:
                _opener_rec['archetype'] = arch
                _opener_rec['archetype_confidence'] = profile.get('confidence', 'low')
                _opener_rec['archetype_reason'] = profile.get('reason', '')
                _opener_rec['exploit'] = meta.get('exploit', '')
                _opener_rec['evidence_hand_ids'] = _prior_examples[:10]


def find_misplays_vs_archetype(hands, profiles):
    """Find hands where Hero likely misplayed against a known archetype.

    Returns a list of dicts with hand_id, archetype, misplay_type, what_to_do.
    """
    misplays = []
    for h in hands:
        if not isinstance(h, dict):
            continue
        arch = h.get('villain_archetype', '')
        if not arch or arch in ('UNKNOWN', 'TAG', 'SOLID_REG'):
            continue
        # B-V10: only flag misplays against medium+ confidence villains.
        # Low-confidence tags (< 20 hands or no showdowns) are unreliable.
        _v_conf = h.get('villain_archetype_confidence', 'low')
        if _v_conf == 'low':
            continue
        hid = h.get('id', '')
        net = h.get('net_bb', 0)
        hsa = h.get('hero_street_actions', {}) or {}
        went_sd = h.get('went_to_sd', False)
        meta = ARCHETYPES.get(arch, {})

        misplay = None

        if arch in ('CALLING_STATION', 'WHALE', 'FISH'):
            # Misplay: bluffing a sticky player (they call everything)
            river_act = hsa.get('river', '')
            if river_act in ('bet', 'raise', 'cbet') and net < -10 and not went_sd:
                misplay = {
                    'misplay_type': f'Bluffed a {meta["label"].lower()} on the river',
                    'what_to_do': f'{meta["label"]}s call too wide — only value-bet, '
                                  f'never bluff. Check back anything you can\'t bet for value.',
                }
            # Misplay: folding to their rare raise (it's always the nuts)
            # (Not implemented yet — would need per-street villain action data)

        elif arch == 'MANIAC':
            # Misplay: folding too much vs constant aggression
            if net < -5 and hsa.get('river') == 'fold' and (h.get('hero_committed_bb', 0) or 0) > 10:
                misplay = {
                    'misplay_type': f'Folded to a {meta["label"].lower()}\'s aggression '
                                    f'with pot committed',
                    'what_to_do': 'Maniacs over-bluff — widen your call-down range. '
                                  'With pot commitment, calling is often +EV. Trap more.',
                }

        elif arch == 'NIT':
            # Misplay: calling a nit's raise with marginal hands
            if h.get('hero_3bet') is False and h.get('vpip') and net < -15:
                misplay = {
                    'misplay_type': f'Called a {meta["label"].lower()}\'s raise with a marginal hand',
                    'what_to_do': 'Nits only raise premium hands. Fold marginal holdings '
                                  'to their aggression — they are never bluffing.',
                }

        elif arch in ('LAG', 'DANGER_REG'):
            # Misplay: hero-calling their multi-street barrels
            turn_act = hsa.get('turn', '')
            river_act = hsa.get('river', '')
            if turn_act == 'call' and river_act == 'call' and net < -20:
                misplay = {
                    'misplay_type': f'Hero-called a {meta["label"].lower()}\'s multi-street barrel',
                    'what_to_do': f'{meta["label"]}s are value-heavy on big multi-street lines. '
                                  f'Raise for information on the turn or fold — don\'t call down passively.',
                }

        elif arch == 'FUN_REC':
            # Misplay: fancy bluff against a rec player
            if hsa.get('river') in ('bet', 'raise') and net < -10 and not went_sd:
                misplay = {
                    'misplay_type': f'Ran a fancy bluff against a {meta["label"].lower()}',
                    'what_to_do': 'Rec players call too much and don\'t respect '
                                  'sophisticated lines. Simplify — bet value, check the rest.',
                }

        if misplay:
            misplays.append({
                'hand_id': hid,
                'archetype': arch,
                'archetype_label': h.get('villain_archetype_label', ''),
                'villain_reason': h.get('villain_archetype_reason', ''),
                'villain_hids': h.get('villain_example_hids', []),
                **misplay,
            })

    return misplays
