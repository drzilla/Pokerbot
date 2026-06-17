"""Issue Collector v2 — table-based triage system for poker leaks.

Every issue is a clickable object with the chain:
  issue -> severity -> confidence -> why it matters -> where it happens
  -> exact hands -> what I did -> what I should do -> drill/training

Four tiers: confirmed | candidate | shadow | cleared
Training objects on every issue (even if status is 'unavailable').
Postflop Action Drill-Down rows for postflop issues.

v8.2.0 (2026-06-03)
"""

from collections import defaultdict


# ── Priority scoring ──────────────────────────────────────────────────

def _priority_score(issue):
    """Compute priority ranking. Higher = fix first.

    Formula: tier_weight + severity + confidence + recurrence + EV/frequency + drillability.
    Confirmed/Fix Now outranks Candidate unless Candidate has huge evidence.
    """
    # Tier weight dominates — confirmed always outranks candidate by default
    _tier_w = {'confirmed': 100, 'candidate': 50, 'shadow': 20, 'cleared': 0}.get(
        issue.get('tier', 'shadow'), 10)
    _sev_w = {'critical': 30, 'high': 20, 'medium': 10, 'low': 5, 'info': 0}.get(
        issue.get('severity', 'low'), 5)
    _conf_w = {'high': 15, 'medium': 10, 'low': 5, 'mixed': 7}.get(
        issue.get('confidence', 'low'), 5)
    _ev = issue.get('evidence', {})
    _recurrence = (_ev.get('recurrence_sessions') or 0) * 5
    _freq = min((_ev.get('frequency') or 0) * 0.5, 20)  # cap at 20
    _ev_cost = min(abs(_ev.get('cost_bb_per_100') or 0) * 2, 30)  # cap at 30
    _train = issue.get('training', {})
    _drill_w = 10 if _train.get('type') in ('gtowizard_drill', 'gtowizard_node', 'pokerbot_drill') else (
        5 if _train.get('type') == 'review' and _train.get('source_hand_ids') else 0)
    return round(_tier_w + _sev_w + _conf_w + _recurrence + _freq + _ev_cost + _drill_w, 1)


def _make_training(type_='review', label='Review Hands', url=None,
                   status='needs_review', hand_ids=None, spot_count=0,
                   description='', method='review_only', setup=None):
    """Build a training object."""
    t = {
        'type': type_,
        'label': label,
        'url': url,
        'status': status,
        'source_hand_ids': hand_ids or [],
        'spot_count': spot_count,
        'description': description,
        'generation_method': method,
    }
    if setup:
        t['setup_parameters'] = setup
    return t


def _make_where(streets=None, positions=None, pot_types=None,
                hero_roles=None, stack_depths=None, board_textures=None,
                spot_type=''):
    """Build a 'where' descriptor."""
    return {
        'streets': streets or [],
        'positions': positions or [],
        'pot_types': pot_types or [],
        'hero_roles': hero_roles or [],
        'stack_depths': stack_depths or [],
        'board_textures': board_textures or [],
        'spot_type': spot_type,
    }


def _make_evidence(frequency=0, sample_size=0, cost_bb_per_100=None,
                   ev_estimate='', delta_vs_target=None,
                   recurrence_sessions=None, summary=''):
    """Build an evidence block."""
    return {
        'frequency': frequency,
        'sample_size': sample_size or frequency,
        'cost_bb_per_100': cost_bb_per_100,
        'ev_estimate': ev_estimate,
        'delta_vs_target': delta_vs_target,
        'recurrence_sessions': recurrence_sessions,
        'summary': summary,
    }


def _make_evidence_quality(sample=0, auto=0, analyst=0, solver=0, counter=0):
    """Build evidence_quality block."""
    return {
        'sample_size': sample,
        'auto_scored': auto,
        'analyst_reviewed': analyst,
        'solver_checked': solver,
        'counterexamples': counter,
    }


def _classify_board_texture(board):
    """Simple board texture classifier from card list."""
    if not board or len(board) < 3:
        return ''
    # Very rough — the real classifier is in gem_analyzer
    suits = [c[-1] for c in board[:3] if len(c) >= 2]
    if len(set(suits)) == 1:
        return 'monotone'
    ranks = []
    _RV = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8,
           '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
    for c in board[:3]:
        r = c[0] if len(c) >= 2 else ''
        ranks.append(_RV.get(r, 0))
    ranks.sort()
    hi = max(ranks) if ranks else 0
    spread = (ranks[-1] - ranks[0]) if len(ranks) >= 2 else 0
    if hi >= 14:
        return 'A-high dry' if spread > 5 else 'A-high connected'
    if hi >= 13:
        return 'K-high'
    if spread <= 4 and 5 <= hi <= 11:
        return 'connected middling'
    if len(set(ranks)) < len(ranks):
        return 'paired'
    if spread <= 3:
        return 'connected'
    return 'dry'


# ── Main collector ────────────────────────────────────────────────────

def collect_issues(stats, rd, hands):
    """Collect issues from all pipeline sources.

    Returns list of issue dicts (full v2 schema), sorted by priority descending.
    """
    issues = []
    _hbi = {h.get('id'): h for h in hands if h.get('id')}
    analyst = rd.get('analyst_commentary', {}) or {}
    n_hands = len(hands) or 1
    _phids = stats.get('popup_hand_ids', {}) or {}
    _analyst_ids = {h for h, c in analyst.items()
                    if isinstance(c, dict) and h.startswith('TM')}

    # ================================================================
    # SOURCE 1: Promoted leaks (leak_persistence) → Confirmed
    # ================================================================
    persistence = (rd.get('leak_persistence') or {}).get('current_leaks', [])
    for leak in (persistence or []):
        if not isinstance(leak, dict):
            continue
        name = leak.get('name', leak.get('leak', ''))
        if not name:
            continue
        _freq = leak.get('hands_flagged', 0)
        _sess = leak.get('sessions_seen', 1)
        issues.append({
            'id': f'promoted_{name.lower().replace(" ", "_")[:40]}',
            'name': name,
            'tier': 'confirmed',
            'severity': 'high',
            'confidence': 'high',
            'diagnosis': f'Persistent leak across {_sess} session(s).',
            'why_it_matters': leak.get('why', 'Repeated pattern costs EV over time.'),
            'evidence': _make_evidence(
                frequency=_freq, cost_bb_per_100=leak.get('ev_cost_per_100'),
                recurrence_sessions=_sess,
                summary=f'{_freq} flagged hands, seen in {_sess} session(s).'),
            'where': _make_where(spot_type='promoted_leak'),
            'representative_hands': {'clean_mistake': [], 'boundary': [], 'counterexample': []},
            'all_hand_ids': [],
            'correct_action': leak.get('action', ''),
            'exception': '',
            'memory_rule': '',
            'source_provenance': [{'section': 'Leak Persistence', 'detector': 'leak_persistence', 'confidence': 'high'}],
            'evidence_quality': _make_evidence_quality(sample=_freq),
            'status': 'recurring' if _sess > 1 else 'new',
            'training': _make_training(
                type_='review', label='Review Hands', status='needs_review',
                spot_count=_freq, description=f'Review {_freq} flagged hands for {name}.'),
        })

    # ================================================================
    # SOURCE 2: Watchlist red/amber metrics → Confirmed/Candidate
    # ================================================================
    # KPI→poker behavior translation: abstract metrics become actionable issues
    _KPI_BEHAVIOR = {
        'VPIP': {
            'name': 'Playing too many hands preflop',
            'diagnosis': 'VPIP above target — entering pots with marginal holdings.',
            'why': 'Wide VPIP bleeds chips in raised pots with dominated hands.',
            'where': _make_where(streets=['preflop'], spot_type='vpip'),
            'action': 'Tighten opening ranges, especially from EP and MP.',
        },
        'PFR': {
            'name': 'Preflop raise rate outside target',
            'diagnosis': 'PFR deviation — either too passive (limping) or over-raising.',
            'why': 'PFR/VPIP gap reveals limping or cold-calling excess.',
            'where': _make_where(streets=['preflop'], spot_type='pfr'),
            'action': 'Raise or fold; minimize limp-calls.',
        },
        'VPIP_PFR_GAP': {
            'name': 'Too much cold-calling, not enough raising',
            'diagnosis': 'VPIP/PFR gap too wide — calling where raising is better.',
            'why': 'Cold-calling without initiative costs equity postflop.',
            'where': _make_where(streets=['preflop'], spot_type='vpip_pfr_gap'),
            'action': 'Convert cold-calls to 3-bets or folds.',
        },
        'AF': {
            'name': 'Postflop aggression out of balance',
            'diagnosis': 'AF deviation — too passive or too aggressive after the flop.',
            'why': 'Low AF surrenders initiative; high AF burns thin value.',
            'where': _make_where(streets=['flop', 'turn', 'river'], spot_type='af'),
            'action': 'Bet/raise when you have equity advantage; check-call when not.',
        },
        'ATS': {
            'name': 'Steal frequency outside target',
            'diagnosis': 'Late-position steal rate deviation.',
            'why': 'Under-stealing surrenders dead money; over-stealing increases 3-bet exposure.',
            'where': _make_where(streets=['preflop'], positions=['CO', 'BTN', 'SB'], spot_type='ats'),
            'action': 'Calibrate steal range to table dynamics.',
        },
        'CBET': {
            'name': 'C-bet frequency outside target',
            'diagnosis': 'Continuation bet rate deviation on flop.',
            'why': 'Over-cbetting costs on bad boards; under-cbetting misses value.',
            'where': _make_where(streets=['flop'], hero_roles=['PFR'], spot_type='cbet'),
            'action': 'C-bet on favorable textures; check back on bad boards.',
        },
        'RIVER_BET_AVG': {
            'name': 'River betting frequency imbalanced',
            'diagnosis': 'Betting river too often or not enough.',
            'why': 'River over-aggression turns SDV into bluffs; under-aggression misses thin value.',
            'where': _make_where(streets=['river'], spot_type='river_bet'),
            'action': 'Bet river only when worse calls or better folds exist.',
        },
        'PURE_BLUFF_PCT': {
            'name': 'Not enough selected bluffs',
            'diagnosis': 'Under-bluffing in capped-range spots where villain shows weakness.',
            'why': 'Without balanced bluffs, opponents can over-fold against your value bets.',
            'where': _make_where(streets=['flop', 'turn'], spot_type='bluff_freq'),
            'action': 'Add bluffs with blockers/equity when villain range is capped.',
        },
        'WWSF': {
            'name': 'Win rate when seeing flop is low',
            'diagnosis': 'WWSF below target — losing too many pots after seeing the flop.',
            'why': 'Low WWSF means passive postflop play or poor hand selection.',
            'where': _make_where(streets=['flop', 'turn', 'river'], spot_type='wwsf'),
            'action': 'Be more aggressive postflop when you have equity.',
        },
        'VPIP_PFR_GAP_RAW': {
            'name': 'Too much cold-calling, not enough raising',
            'diagnosis': 'VPIP/PFR gap too wide — flat-calling where 3-betting or folding is better.',
            'why': 'Cold-calling without initiative costs equity postflop.',
            'where': _make_where(streets=['preflop'], spot_type='vpip_pfr_gap'),
            'action': 'Convert cold-calls to 3-bets or folds.',
        },
        'CR_FLOP_PCT': {
            'name': 'Not check-raising flop enough',
            'diagnosis': 'Check-raise frequency below target — missing value and bluff opportunities on the flop.',
            'why': 'Under-check-raising lets opponents realize equity cheaply and denies value.',
            'where': _make_where(streets=['flop'], hero_roles=['caller OOP', 'BB defender'], spot_type='check_raise'),
            'action': 'Check-raise more on boards that favor your range, especially with sets/two-pair and combo draws.',
        },
        'BB_ISO_SB_LIMP': {
            'name': 'Not isolating SB limps from BB',
            'diagnosis': 'BB iso-raise vs SB limp rate outside target.',
            'why': 'Letting SB see cheap flops with a wide limp range surrenders BB equity advantage.',
            'where': _make_where(streets=['preflop'], positions=['BB'], spot_type='bb_iso'),
            'action': 'Raise wider from BB when SB limps — exploit their weak range.',
        },
        'SEMI_BLUFF_PCT': {
            'name': 'Not enough semi-bluffs with draws',
            'diagnosis': 'Semi-bluff frequency below target — checking too many drawing hands.',
            'why': 'Passive draws miss fold equity and let opponents catch up.',
            'where': _make_where(streets=['flop', 'turn'], spot_type='semi_bluff'),
            'action': 'Bet/raise draws with good equity + fold equity, especially with overcards or combo draws.',
        },
        'HERO_4BET_PCT': {
            'name': '4-bet frequency outside target',
            'diagnosis': '4-bet rate deviation — under-4betting loses value vs 3-bettors; over-4betting is exploitable.',
            'why': 'Flat-calling 3-bets OOP with premium hands costs EV vs aggressive opponents.',
            'where': _make_where(streets=['preflop'], spot_type='4bet'),
            'action': 'Expand 4-bet range vs frequent 3-bettors; tighten vs tight players.',
        },
        'ATS_RAW': {
            'name': 'Steal frequency outside target',
            'diagnosis': 'Late-position steal rate deviation (aggregate).',
            'why': 'Under-stealing surrenders dead money; over-stealing increases 3-bet exposure.',
            'where': _make_where(streets=['preflop'], positions=['CO', 'BTN', 'SB'], spot_type='ats'),
            'action': 'Calibrate steal range to table dynamics and players behind.',
        },
        'SMALL_FLOP_CBET_PCT': {
            'name': 'Small-sizing c-bet frequency off target',
            'diagnosis': 'Small flop c-bet rate deviation — over or under-using the small sizing.',
            'why': 'Wrong c-bet sizing frequency lets opponents exploit your range by size.',
            'where': _make_where(streets=['flop'], hero_roles=['PFR'], spot_type='cbet_small'),
            'action': 'Use small c-bet on boards favoring your range; check back on bad textures.',
        },
        'RIVER_BET_AVG_BB': {
            'name': 'River betting frequency imbalanced',
            'diagnosis': 'Betting river too often or too rarely.',
            'why': 'Over-betting river turns SDV into bluffs; under-betting misses thin value.',
            'where': _make_where(streets=['river'], spot_type='river_bet'),
            'action': 'Bet river only when worse calls or better folds exist.',
        },
        'FLOP_CBET_HU_OOP_PCT': {
            'name': 'C-bet out of position frequency off target',
            'diagnosis': 'OOP c-bet rate deviation — usually should c-bet less OOP than IP.',
            'why': 'C-betting OOP into a caller who has position risks getting raised or floated.',
            'where': _make_where(streets=['flop'], hero_roles=['PFR OOP'], spot_type='cbet_oop'),
            'action': 'Check more OOP; c-bet only on boards that strongly favor PFR range.',
        },
        'TRIPLE_BARREL_PCT': {
            'name': 'Triple-barrel frequency outside target',
            'diagnosis': 'Firing three streets too often or not enough.',
            'why': 'Over-barreling river loses to call-down ranges; under-barreling gives up on value.',
            'where': _make_where(streets=['river'], hero_roles=['PFR'], spot_type='triple_barrel'),
            'action': 'Triple-barrel for value with strong hands; bluff only with blockers to villain call range.',
        },
        'COLD_CALL_NB_PCT': {
            'name': 'Cold-calling too much from non-blind positions',
            'diagnosis': 'Cold-call rate outside target — calling raises without initiative.',
            'why': 'Cold-calling without position or equity edge costs chips postflop.',
            'where': _make_where(streets=['preflop'], spot_type='cold_call'),
            'action': '3-bet or fold; only flat suited connectors/pairs in position with good implied odds.',
        },
        'THREEBET_OOP_PCT': {
            'name': '3-bet rate from OOP outside target',
            'diagnosis': '3-bet from out-of-position rate deviation.',
            'why': 'Under-3betting OOP lets openers realize equity; over-3betting expands range too wide.',
            'where': _make_where(streets=['preflop'], positions=['SB', 'BB'], spot_type='3bet_oop'),
            'action': '3-bet premium hands and select bluffs OOP; flat less.',
        },
    }
    # Aliases: map exact watchlist keys to the behavior entries above
    _KPI_ALIASES = {
        'COLD_CALL_NB': 'COLD_CALL_NB_PCT',
        'THREEBET_OOP': 'THREEBET_OOP_PCT',
        'HERO_4BET': 'HERO_4BET_PCT',
        'TRIPLE_BARREL': 'TRIPLE_BARREL_PCT',
        'FLOP_CBET_HU_OOP': 'FLOP_CBET_HU_OOP_PCT',
        'F2_FLOP_CBET_SMALL': 'SMALL_FLOP_CBET_PCT',
        'F2_FLOP_CBET_LARGE': 'CBET',
        'F2_TURN_CBET_SMALL': 'CBET',
        'RIVER_BET_AVG_BB': 'RIVER_BET_AVG_BB',
        'ATS_RAW': 'ATS_RAW',
        'CBET_3BP': 'CBET',
    }
    # Add an entry for the missing Agg_React_Delta
    _KPI_BEHAVIOR['AGG_REACT_DELTA'] = {
        'name': 'Aggression timing inconsistent',
        'diagnosis': 'Delta between aggression on early vs late streets is outside target range.',
        'why': 'Inconsistent aggression across streets makes your line predictable.',
        'where': _make_where(streets=['flop', 'turn', 'river'], spot_type='agg_reaction'),
        'action': 'Keep aggression consistent across streets unless the board changes significantly.',
    }

    wl = rd.get('leak_watchlist', {})
    for item in (wl.get('session_metrics') or []):
        if item.get('status') not in ('red', 'amber'):
            continue
        tier = 'confirmed' if item['status'] == 'red' else 'candidate'
        _metric = item.get('metric', '?')
        _label = item.get('label', _metric)
        if not _label:
            continue
        # Translate generic KPI to poker behavior — check aliases first
        _key_upper = _metric.upper()
        _resolved_key = _KPI_ALIASES.get(_key_upper, _key_upper)
        _behav = _KPI_BEHAVIOR.get(_resolved_key, _KPI_BEHAVIOR.get(_key_upper, {}))
        _name = _behav.get('name', _label)
        _diag = _behav.get('diagnosis', f'{_label} outside target range.')
        _why = _behav.get('why', 'This stat is outside the expected range for your player profile.')
        _act = _behav.get('action', item.get('action', ''))
        _where = _behav.get('where', _make_where(spot_type='metric_deviation'))
        _bds = item.get('sub_breakdowns', [])
        _where_pos = [bd.get('position', '') for bd in _bds if bd.get('status') in ('red', 'amber')]
        if _where_pos and not _where.get('positions'):
            _where['positions'] = _where_pos
        # v8.4.0: gate tier on sample size — small samples shouldn't be "Fix Now"
        _sample_n = item.get('n', item.get('sample', 0)) or 0
        if _sample_n < 15 and tier == 'confirmed':
            tier = 'candidate'
        if _sample_n < 30 and tier == 'confirmed':
            tier = 'candidate'
        _conf = 'low' if _sample_n < 15 else ('medium' if _sample_n < 50 else 'high')
        issues.append({
            'id': f'metric_{_metric}',
            'name': _name,
            'tier': tier,
            'severity': 'high' if item['status'] == 'red' else 'medium',
            'confidence': _conf,
            'diagnosis': _diag,
            'why_it_matters': _why,
            'evidence': _make_evidence(
                delta_vs_target=item.get('delta'),
                summary=item.get('summary', f'{_name}: {item.get("status")} flag.')),
            'where': _where,
            'representative_hands': {'clean_mistake': [], 'boundary': [], 'counterexample': []},
            'all_hand_ids': [],
            'correct_action': _act,
            'exception': '',
            'memory_rule': '',
            'source_provenance': [{'section': item.get('section', ''), 'detector': 'leak_watchlist', 'confidence': 'medium'}],
            'evidence_quality': _make_evidence_quality(),
            'status': item.get('trend', 'new'),
            'training': _make_training(
                type_='review', label='Review Hands', status='needs_review',
                description=_act or f'Review hands where this pattern appears.'),
            'sub_breakdowns': _bds,
        })

    # ================================================================
    # SOURCE 3: Passivity — missed steals → Candidate
    # ================================================================
    _missed_steals = [m for m in stats.get('mistakes', [])
                      if 'Missed Steal' in (m.get('type') or '')]
    if len(_missed_steals) >= 3:
        _ms_ids = [m['id'] for m in _missed_steals if m.get('id')]
        _n = len(_missed_steals)
        issues.append({
            'id': 'passivity_missed_steals',
            'name': 'Missed late-position steals',
            'tier': 'candidate',
            'severity': 'medium' if _n < 10 else 'high',
            'confidence': 'mixed',
            'diagnosis': f'Folded {_n} spots where opening is standard from LP.',
            'why_it_matters': 'Missed steals surrender dead money and reduce win rate.',
            'evidence': _make_evidence(
                frequency=_n, sample_size=_n, ev_estimate='medium',
                summary=f'{_n} missed open/steal opportunities from CO/BTN/SB.'),
            'where': _make_where(
                streets=['preflop'], positions=['CO', 'BTN', 'SB'],
                spot_type='preflop_first_in'),
            'representative_hands': {
                'clean_mistake': _ms_ids[:2],
                'boundary': _ms_ids[2:3] if len(_ms_ids) > 2 else [],
                'counterexample': [],
            },
            'all_hand_ids': _ms_ids,
            'correct_action': 'Open KTo/QTo/J9s-type hands when folded to in LP.',
            'exception': 'Fold bottom range if aggressive 3-bettor behind or ICM spot.',
            'memory_rule': 'Face card + connector in LP = open unless specific reason not to.',
            'source_provenance': [{'section': 'sec-8-1', 'detector': 'missed_steal', 'confidence': 'mixed'}],
            'evidence_quality': _make_evidence_quality(sample=_n, auto=_n),
            'status': 'new',
            'training': _make_training(
                type_='review', label='Review Hands', status='needs_review',
                hand_ids=_ms_ids[:10], spot_count=_n,
                description=f'Review {_n} missed steal spots from LP.',
                setup={'positions': ['CO', 'BTN', 'SB'], 'street': 'preflop',
                       'preflop_action': 'folded_to_hero'}),
        })

    # ================================================================
    # SOURCE 4: Over-folding by position → Candidate
    # ================================================================
    # B146/B160: build deviation lookup so IE drawer can annotate each hand
    _dev_by_id = {}
    for _d in (stats.get('preflop_deviations') or []):
        _did = _d.get('id')
        if _did:
            _dev_by_id[_did] = {'type': _d.get('type', ''), 'chart': _d.get('chart', ''),
                                'confidence': _d.get('confidence', '')}
    for of in (stats.get('overfold_by_position') or []):
        _pos = of.get('position', '?')
        _excess = of.get('excess_pp', 0)
        _fids = of.get('fold_ids', [])
        issues.append({
            'id': f'overfold_{_pos}',
            'name': f'Over-folding from {_pos}',
            'tier': 'candidate',
            'severity': 'medium' if _excess < 15 else 'high',
            'confidence': 'medium',
            'diagnosis': f'Folding {of.get("fold_pct", 0):.0f}% from {_pos} (target ~{of.get("expected_fold_pct", 0):.0f}%).',
            'why_it_matters': 'Excessive folding surrenders equity and makes Hero exploitable.',
            'evidence': _make_evidence(
                frequency=of.get('sample', 0),
                delta_vs_target=f'{of.get("fold_pct", 0):.0f}% vs {of.get("expected_fold_pct", 0):.0f}% target',
                summary=f'{_pos}: fold {of.get("fold_pct", 0):.0f}% (target ~{of.get("expected_fold_pct", 0):.0f}%)'),
            'where': _make_where(
                streets=['preflop'], positions=[_pos], spot_type='open_defend'),
            'representative_hands': {
                'clean_mistake': _fids[:2], 'boundary': _fids[2:3], 'counterexample': []},
            'all_hand_ids': _fids,
            'hand_deviations': {
                **{hid: _dev_by_id[hid] for hid in _fids if hid in _dev_by_id},
                **{hid: {'type': 'Missed Open', 'chart': note.split(' — ')[0] if ' — ' in note else '',
                         'confidence': 'CLEAR'}
                   for hid, note in (of.get('fold_range_notes') or {}).items()
                   if hid not in _dev_by_id},
            },
            'correct_action': f'Open/defend wider from {_pos}.',
            'exception': 'Tighten vs aggressive 3-bettors or deep ICM.',
            'memory_rule': '',
            'source_provenance': [{'section': 'sec-8-1', 'detector': 'overfold_analysis', 'confidence': 'medium'}],
            'evidence_quality': _make_evidence_quality(sample=of.get('sample', 0), auto=len(_fids)),
            'status': 'new',
            'training': _make_training(
                type_='review', label='Review Hands', status='needs_review',
                hand_ids=_fids[:10], spot_count=len(_fids),
                description=f'Review {len(_fids)} folds from {_pos} that may be too tight.'),
        })

    # ================================================================
    # SOURCE 4b: Missed check-raises → Candidate (when CR% below target)
    # ================================================================
    _mcr_ids = _phids.get('missed_cr_flop_ids', [])
    if len(_mcr_ids) >= 3:
        issues.append({
            'id': 'missed_check_raises',
            'name': 'Missed check-raise opportunities on flop',
            'tier': 'candidate',
            'severity': 'medium',
            'confidence': 'medium',
            'diagnosis': f'{len(_mcr_ids)} spots where Hero had a strong hand OOP vs c-bet and just called instead of check-raising.',
            'why_it_matters': 'Check-raising with strong hands builds pots, denies equity, and balances your check-raise range.',
            'evidence': _make_evidence(
                frequency=len(_mcr_ids),
                summary=f'{len(_mcr_ids)} flop check-raise opportunities missed (had two-pair+ OOP vs c-bet).'),
            'where': _make_where(
                streets=['flop'], hero_roles=['caller OOP', 'BB defender'],
                spot_type='check_raise'),
            'representative_hands': {
                'clean_mistake': _mcr_ids[:2],
                'boundary': _mcr_ids[2:3] if len(_mcr_ids) > 2 else [],
                'counterexample': [],
            },
            'all_hand_ids': _mcr_ids,
            'correct_action': 'Check-raise strong hands (two-pair+, sets, combo draws) on flop when OOP vs c-bet.',
            'exception': 'Flat-call when board heavily favors c-bettor range or when trapping is higher EV.',
            'memory_rule': 'Strong hand OOP vs c-bet = consider check-raise before calling.',
            'source_provenance': [{'section': 'sec-13-3', 'detector': 'missed_cr_flop', 'confidence': 'medium'}],
            'evidence_quality': _make_evidence_quality(sample=len(_mcr_ids), auto=len(_mcr_ids)),
            'status': 'new',
            'training': _make_training(
                type_='review', label='Review Hands', status='needs_review',
                hand_ids=_mcr_ids[:10], spot_count=len(_mcr_ids),
                description=f'Review {len(_mcr_ids)} flop spots where check-raising was an option.',
                setup={'street': 'flop', 'hero_role': 'caller OOP', 'action_node': 'check_raise_vs_cbet'}),
        })

    # ================================================================
    # SOURCE 5: Coaching flags → Candidate
    # ================================================================
    _cf_rules = defaultdict(list)
    for cf in (stats.get('coaching_flags') or []):
        _cf_rules[cf.get('rule', '?')].append(cf)
    _cf_labels = {
        'MW_SMALL_SIZING': ('MW pot: sizing too small', 'Multiway pots need larger sizing with value hands to charge draws.'),
        'OOP_CHECK_CALL_SHOULD_BET': ('OOP passive: should bet', 'Check-calling where betting is better for protection or value.'),
        'CHEAP_TOURNEY_SMALL_SIZING': ('Cheap tourney: size up', 'Value bets too small in low-stakes — size up vs calling stations.'),
        'BVB_DEEP_RAGGED_OPEN': ('BvB deep: don\'t open bottom', 'Opening bottom range BvB deep is -EV vs competent blinds.'),
    }
    for rule, items in _cf_rules.items():
        _ids = [it['id'] for it in items if it.get('id')]
        _lab, _diag = _cf_labels.get(rule, (rule.replace('_', ' '), ''))
        if not _lab:
            continue
        issues.append({
            'id': f'coaching_{rule.lower()[:40]}',
            'name': _lab,
            'tier': 'candidate',
            'severity': 'low',
            'confidence': 'medium',
            'diagnosis': _diag,
            'why_it_matters': 'Auto-coach flagged a repeating pattern worth reviewing.',
            'evidence': _make_evidence(
                frequency=len(items),
                summary=f'{len(items)} spots flagged by coaching rule.'),
            'where': _make_where(spot_type='coaching_rule'),
            'representative_hands': {'clean_mistake': _ids[:2], 'boundary': [], 'counterexample': []},
            'all_hand_ids': _ids,
            'correct_action': items[0].get('detail', '') if items else '',
            'exception': '',
            'memory_rule': '',
            'source_provenance': [{'section': '', 'detector': f'coaching_{rule}', 'confidence': 'medium'}],
            'evidence_quality': _make_evidence_quality(sample=len(items), auto=len(_ids)),
            'status': 'new',
            'training': _make_training(
                type_='review', label='Review Hands', status='needs_review',
                hand_ids=_ids[:10], spot_count=len(items),
                description=f'Review {len(items)} spots for {_lab}.'),
        })

    # ================================================================
    # SOURCE 6: Facing-bets over-folding by street/size → Candidate (NEW)
    # ================================================================
    _fvb = stats.get('fold_vs_bet_by_sizing', {}) or {}
    for bucket, data in _fvb.items():
        _fold_pct = data.get('fold_pct', 0)
        _target = data.get('target_max', 50)
        _excess = _fold_pct - _target
        if _excess < 10 or data.get('opps', 0) < 5:
            continue
        _fids = data.get('fold_ids', [])
        _cids = data.get('call_ids', [])
        issues.append({
            'id': f'facing_bet_overfold_{bucket}',
            'name': f'Over-folding vs {bucket} bets',
            'tier': 'candidate',
            'severity': 'medium' if _excess < 20 else 'high',
            'confidence': 'medium',
            'diagnosis': f'Folding {_fold_pct:.0f}% vs {bucket} bets (target: under {_target}%).',
            'why_it_matters': 'Over-folding vs bets lets opponents profit by bluffing.',
            'evidence': _make_evidence(
                frequency=len(_fids), sample_size=data.get('opps', 0),
                delta_vs_target=f'{_fold_pct:.0f}% vs {_target}% target',
                summary=f'Fold {_fold_pct:.0f}% vs {bucket} ({data.get("opps", 0)} opps, target under {_target}%)'),
            'where': _make_where(
                streets=['flop', 'turn', 'river'], spot_type='facing_bet'),
            'representative_hands': {
                'clean_mistake': _fids[:2], 'boundary': _cids[:1], 'counterexample': []},
            'all_hand_ids': _fids,
            'correct_action': f'Defend more vs {bucket} bets — call with marginal made hands.',
            'exception': 'Fold when board texture heavily favors bettor range.',
            'memory_rule': '',
            'source_provenance': [{'section': 'sec-11-7', 'detector': 'fold_vs_bet_sizing', 'confidence': 'medium'}],
            'evidence_quality': _make_evidence_quality(sample=data.get('opps', 0), auto=len(_fids)),
            'status': 'new',
            'training': _make_training(
                type_='review', label='Review Hands', status='needs_review',
                hand_ids=_fids[:10], spot_count=len(_fids),
                description=f'Review {len(_fids)} folds vs {bucket} bets.'),
        })

    # ================================================================
    # SOURCE 7: River over-aggression / bad bet-check → Candidate (NEW)
    # ================================================================
    _river_hands = [h for h in hands if len(h.get('board', [])) >= 5 and h.get('vpip')]
    _river_bets = [h for h in _river_hands
                   if any(a.get('street') == 'river' and a.get('action') in ('bet', 'raise')
                          for a in h.get('action_ledger', []))]
    _river_checks = [h for h in _river_hands
                     if any(a.get('street') == 'river' and a.get('action') == 'check'
                            for a in h.get('action_ledger', []))]
    _river_sample = len(_river_bets) + len(_river_checks)
    if _river_sample >= 10:
        _river_bet_pct = len(_river_bets) / _river_sample * 100
        if _river_bet_pct > 55:  # over-betting river
            _rb_ids = [h['id'] for h in _river_bets if h.get('id')]
            issues.append({
                'id': 'river_over_aggression',
                'name': 'River over-aggression',
                'tier': 'candidate',
                'severity': 'medium',
                'confidence': 'low',
                'diagnosis': f'Betting {_river_bet_pct:.0f}% of river decisions ({len(_river_bets)}/{_river_sample}).',
                'why_it_matters': 'Betting marginal SDV on river burns EV — worse hands fold, better hands call.',
                'evidence': _make_evidence(
                    frequency=len(_river_bets), sample_size=_river_sample,
                    ev_estimate='medium',
                    summary=f'{len(_river_bets)}/{_river_sample} river spots bet (target ~40-50%).'),
                'where': _make_where(
                    streets=['river'], pot_types=['SRP', '3BP'],
                    hero_roles=['PFR IP', 'PFR OOP', 'caller IP'],
                    spot_type='river_bet_check_decision'),
                'representative_hands': {
                    'clean_mistake': _rb_ids[:2], 'boundary': _rb_ids[2:3], 'counterexample': []},
                'all_hand_ids': _rb_ids,
                'correct_action': 'Check back marginal SDV unless you can name worse calls or better folds.',
                'exception': 'Bet when villain is capped and population over-folds.',
                'memory_rule': 'Before betting river, name worse calls and better folds. If I cannot, check.',
                'source_provenance': [{'section': 'sec-11', 'detector': 'river_bet_check', 'confidence': 'low'}],
                'evidence_quality': _make_evidence_quality(sample=_river_sample, auto=len(_rb_ids)),
                'status': 'new',
                'training': _make_training(
                    type_='review', label='Review Hands', status='needs_review',
                    hand_ids=_rb_ids[:10], spot_count=len(_rb_ids),
                    description='Review river bet/check decisions where Hero bet marginal SDV.',
                    setup={'street': 'river', 'action_node': 'bet_or_check'}),
                'postflop_action_drilldown': _build_river_drilldown(_river_bets, _hbi),
            })

    # ================================================================
    # SOURCE 8: Missed aggression clusters → Candidate (NEW)
    # ================================================================
    _af_data = stats.get('af_breakdown', {}) or {}
    _low_af_spots = []
    for key, data in _af_data.items():
        if isinstance(data, dict) and data.get('af', 99) < 1.5 and data.get('n', 0) >= 8:
            _low_af_spots.append((key, data))
    if _low_af_spots:
        _all_passive_ids = []
        for _, data in _low_af_spots:
            _all_passive_ids.extend(data.get('passive_ids', []))
        _spots_desc = ', '.join(k for k, _ in _low_af_spots[:3])
        issues.append({
            'id': 'missed_aggression_cluster',
            'name': 'Missed aggression spots',
            'tier': 'candidate',
            'severity': 'medium',
            'confidence': 'low',
            'diagnosis': f'Low AF ({_spots_desc}) — passive where raising/betting expected.',
            'why_it_matters': 'Missing aggression in high-equity spots leaves value on the table.',
            'evidence': _make_evidence(
                frequency=len(_all_passive_ids),
                summary=f'{len(_low_af_spots)} spot types with AF < 1.5.'),
            'where': _make_where(
                streets=['flop', 'turn'], hero_roles=['caller IP', 'caller OOP'],
                spot_type='missed_aggression'),
            'representative_hands': {
                'clean_mistake': _all_passive_ids[:2], 'boundary': [], 'counterexample': []},
            'all_hand_ids': _all_passive_ids,
            'correct_action': 'Raise or bet more in spots where Hero has equity advantage.',
            'exception': 'Stay passive vs strong ranges or when pot control is correct.',
            'memory_rule': '',
            'source_provenance': [{'section': 'sec-13', 'detector': 'af_breakdown', 'confidence': 'low'}],
            'evidence_quality': _make_evidence_quality(sample=len(_all_passive_ids), auto=len(_all_passive_ids)),
            'status': 'new',
            'training': _make_training(
                type_='review', label='Review Hands', status='needs_review',
                hand_ids=_all_passive_ids[:10], spot_count=len(_all_passive_ids),
                description='Review passive spots where aggression was expected.'),
        })

    # ================================================================
    # SOURCE 9: Recurring -EV line classes → Shadow (enhanced)
    # ================================================================
    for ln in (stats.get('top_losing_lines') or [])[:5]:
        if ln.get('count', 0) < 8 or ln.get('net_bb', 0) >= -10:
            continue
        _line = ln.get('line', '?')
        _line_display = _line.replace('_', ' ')
        _hids_ln = (ln.get('top3_worst', []) + ln.get('top3_best', []))[:10]
        # Parse line for where info
        _streets = []
        if 'river' in _line.lower():
            _streets.append('river')
        if 'turn' in _line.lower():
            _streets.append('turn')
        if 'flop' in _line.lower():
            _streets.append('flop')
        if 'PF' in _line or 'preflop' in _line.lower():
            _streets.append('preflop')
        _pot_types = []
        if 'SRP' in _line:
            _pot_types.append('SRP')
        if '3BP' in _line:
            _pot_types.append('3BP')
        issues.append({
            'id': f'line_{_line[:30]}',
            'name': f'Recurring -EV line: {_line_display[:50]}',
            'tier': 'shadow',
            'severity': 'medium',
            'confidence': 'low',
            'diagnosis': f'{ln["count"]} hands in this line, net {ln["net_bb"]:+.0f}BB.',
            'why_it_matters': 'Repeating -EV patterns compound over many hands.',
            'evidence': _make_evidence(
                frequency=ln['count'],
                cost_bb_per_100=round(ln.get('avg_bb', 0) * 100 / max(n_hands, 1), 2) if ln.get('avg_bb') else None,
                summary=f'{ln["count"]}x, net {ln["net_bb"]:+.0f}BB this session.'),
            'where': _make_where(
                streets=_streets or ['multi-street'],
                pot_types=_pot_types, spot_type='line_class'),
            'representative_hands': {
                'clean_mistake': _hids_ln[:2], 'boundary': [], 'counterexample': _hids_ln[-1:]},
            'all_hand_ids': _hids_ln,
            'correct_action': '',
            'exception': '',
            'memory_rule': '',
            'source_provenance': [{'section': 'sec-1-2', 'detector': 'line_clustering', 'confidence': 'low'}],
            'evidence_quality': _make_evidence_quality(sample=ln['count'], auto=len(_hids_ln)),
            'status': 'new',
            'training': _make_training(
                type_='review', label='Review Hands', status='needs_review',
                hand_ids=_hids_ln, spot_count=ln['count'],
                description=f'Review {ln["count"]} hands in line class: {_line_display[:40]}.'),
        })

    # ================================================================
    # SOURCE 10: Sizing tell → Shadow
    # ================================================================
    st = stats.get('sizing_tell', {})
    if st.get('is_tell'):
        issues.append({
            'id': 'sizing_tell',
            'name': 'Sizing tell detected',
            'tier': 'shadow',
            'severity': 'medium',
            'confidence': 'low',
            'diagnosis': f'Value bets avg {st["value_avg_bb"]:.1f}BB, bluffs avg {st["bluff_avg_bb"]:.1f}BB.',
            'why_it_matters': 'Predictable bet sizing lets opponents exploit your range.',
            'evidence': _make_evidence(
                frequency=st.get('value_n', 0) + st.get('bluff_n', 0),
                summary=f'Value {st["value_avg_bb"]:.1f}BB vs bluff {st["bluff_avg_bb"]:.1f}BB.'),
            'where': _make_where(streets=['flop', 'turn', 'river'], spot_type='sizing_tell'),
            'representative_hands': {'clean_mistake': [], 'boundary': [], 'counterexample': []},
            'all_hand_ids': [],
            'correct_action': 'Vary bet sizes — use same sizing for value and bluffs.',
            'exception': '',
            'memory_rule': 'Same sizing, different hands.',
            'source_provenance': [{'section': '', 'detector': 'sizing_tell', 'confidence': 'low'}],
            'evidence_quality': _make_evidence_quality(sample=st.get('value_n', 0) + st.get('bluff_n', 0)),
            'status': 'new',
            'training': _make_training(type_='none', label='No Drill', status='unavailable',
                                       description='Awareness item — no specific drill.'),
        })

    # ================================================================
    # SOURCE 11: Tilt cascades → Shadow
    # ================================================================
    for tc in (stats.get('tilt_cascades') or []):
        issues.append({
            'id': f'tilt_{tc.get("trigger_id", "?")}',
            'name': 'Tilt cascade detected',
            'tier': 'shadow',
            'severity': 'high',
            'confidence': 'medium',
            'diagnosis': f'After {tc["trigger_loss_bb"]:+.0f}BB loss, {tc.get("mistakes_in_window", 0)} mistakes in next 20 hands.',
            'why_it_matters': 'Tilt cascades compound losses exponentially.',
            'evidence': _make_evidence(
                frequency=tc.get('mistakes_in_window', 0),
                summary=f'{tc.get("mistakes_in_window", 0)} errors after big loss.'),
            'where': _make_where(spot_type='tilt_cascade'),
            'representative_hands': {'clean_mistake': [tc.get('trigger_id', '')], 'boundary': [], 'counterexample': []},
            'all_hand_ids': [tc.get('trigger_id', '')],
            'correct_action': 'After big losses, pause or tighten ranges for 20 hands.',
            'exception': '',
            'memory_rule': 'Lost big? Take a 2-minute break before the next hand.',
            'source_provenance': [{'section': '', 'detector': 'tilt_detector', 'confidence': 'medium'}],
            'evidence_quality': _make_evidence_quality(sample=tc.get('mistakes_in_window', 0)),
            'status': 'new',
            'training': _make_training(type_='none', label='No Drill', status='unavailable',
                                       description='Mental game — pause after big losses.'),
        })

    # ================================================================
    # SOURCE 12: Blind-spot audit / detector gap → Shadow (NEW)
    # ================================================================
    # Sample unflagged VPIP hands to see if detectors are missing things
    _flagged_ids = set()
    for m in stats.get('mistakes', []):
        if m.get('id'):
            _flagged_ids.add(m['id'])
    for p in (stats.get('punts', {}) or {}).get('hands', []):
        if p.get('id'):
            _flagged_ids.add(p['id'])
    _unflagged_vpip = [h for h in hands
                       if h.get('vpip') and h.get('id') and h['id'] not in _flagged_ids
                       and h.get('net_bb', 0) < -5]
    if len(_unflagged_vpip) >= 10:
        _uf_ids = [h['id'] for h in sorted(_unflagged_vpip, key=lambda x: x.get('net_bb', 0))[:15]]
        issues.append({
            'id': 'blindspot_audit',
            # v8.17.1 P0C: user-facing copy (internal id 'blindspot_audit' stays
            # stable for routing/joins); the prior label was internal detector
            # jargon that read as meaningless in the Leak/Issue Explorer.
            'name': 'Losing hands not explained by current detectors — spot-check sample',
            'tier': 'shadow',
            'severity': 'low',
            'confidence': 'low',
            'diagnosis': f'{len(_unflagged_vpip)} unflagged VPIP hands lost >5BB each.',
            'why_it_matters': 'Some losing patterns may not be flagged by any detector.',
            'evidence': _make_evidence(
                frequency=len(_unflagged_vpip),
                summary=f'{len(_unflagged_vpip)} losing hands with no detector flag.'),
            'where': _make_where(spot_type='detector_gap'),
            'representative_hands': {'clean_mistake': _uf_ids[:2], 'boundary': [], 'counterexample': []},
            'all_hand_ids': _uf_ids,
            'correct_action': 'Review a sample of unflagged losing hands for missed patterns.',
            'exception': 'Many of these may be variance. Look for repeating error types.',
            'memory_rule': '',
            'source_provenance': [{'section': '', 'detector': 'blindspot_sampler', 'confidence': 'low'}],
            'evidence_quality': _make_evidence_quality(sample=len(_unflagged_vpip), auto=0),
            'status': 'new',
            'training': _make_training(
                type_='review', label='Review Hands', status='needs_review',
                hand_ids=_uf_ids, spot_count=len(_unflagged_vpip),
                description=f'Review {len(_uf_ids)} unflagged losing hands for missed errors.'),
        })

    # ================================================================
    # SOURCE 13: Aggression calibration conflict → Shadow (NEW)
    # ================================================================
    # Detect if some spots say "be more aggressive" and others say "less"
    _wants_more_agg = [i for i in issues if 'missed aggression' in i.get('name', '').lower()
                       or 'missed' in i.get('name', '').lower() and 'steal' in i.get('name', '').lower()]
    _wants_less_agg = [i for i in issues if 'over-aggression' in i.get('name', '').lower()
                       or 'sizing tell' in i.get('name', '').lower()]
    if _wants_more_agg and _wants_less_agg:
        issues.append({
            'id': 'aggression_calibration_conflict',
            'name': 'Aggression calibration inconsistent',
            'tier': 'shadow',
            'severity': 'medium',
            'confidence': 'low',
            'diagnosis': 'Some spots need more aggression, others need less. Calibrate by street/spot.',
            'why_it_matters': 'Contradictory adjustments cancel out. Target specific spots, not global AF.',
            'evidence': _make_evidence(
                summary=f'{len(_wants_more_agg)} "be more aggressive" + {len(_wants_less_agg)} "be less aggressive" issues.'),
            'where': _make_where(spot_type='meta_calibration'),
            'representative_hands': {'clean_mistake': [], 'boundary': [], 'counterexample': []},
            'all_hand_ids': [],
            'correct_action': 'Increase flop/turn aggression selectively. Reduce river over-betting. Check-raise only in correct nodes.',
            'exception': '',
            'memory_rule': 'Aggression is spot-specific, not a global dial.',
            'source_provenance': [{'section': '', 'detector': 'meta_conflict', 'confidence': 'low'}],
            'evidence_quality': _make_evidence_quality(),
            'status': 'new',
            'training': _make_training(type_='none', label='No Drill', status='unavailable',
                                       description='Meta-issue: review child issues separately.'),
        })

    # ================================================================
    # SOURCE 14: Analyst-cleared hands → Cleared
    # ================================================================
    _cleared_ids = []
    for hid, cmt in analyst.items():
        if not isinstance(cmt, dict) or not hid.startswith('TM'):
            continue
        v = cmt.get('verdict', '')
        if v.startswith(('III.0', 'III.3', 'III.5', 'I.7')):
            _cleared_ids.append(hid)
    if _cleared_ids:
        issues.append({
            'id': 'cleared_batch',
            # v8.17.1 P0C: user-facing copy (id 'cleared_batch' stays stable);
            # the prior label was internal review-bucket jargon.
            'name': f'{len(_cleared_ids)} hands reviewed and cleared',
            'tier': 'cleared',
            'severity': 'info',
            'confidence': 'high',
            'diagnosis': 'These spots looked suspicious but were cleared by analyst or GTO check.',
            'why_it_matters': 'Proves the system can distinguish real leaks from variance.',
            'evidence': _make_evidence(
                frequency=len(_cleared_ids),
                summary=f'{len(_cleared_ids)} hands cleared after review.'),
            'where': _make_where(spot_type='cleared'),
            'representative_hands': {'clean_mistake': [], 'boundary': [], 'counterexample': _cleared_ids[:3]},
            'all_hand_ids': _cleared_ids,
            'correct_action': 'No action needed — variance or correct play.',
            'exception': '',
            'memory_rule': '',
            'source_provenance': [{'section': 'sec-13', 'detector': 'analyst_verdicts', 'confidence': 'high'}],
            'evidence_quality': _make_evidence_quality(
                sample=len(_cleared_ids), analyst=len(_cleared_ids)),
            'status': 'cleared',
            'training': _make_training(type_='none', label='No Drill', status='unavailable',
                                       description='Cleared — no training needed.'),
        })

    # ================================================================
    # Compute priority scores, assign rank, sort
    # ================================================================
    for issue in issues:
        issue['priority_score'] = _priority_score(issue)
    issues.sort(key=lambda x: -x['priority_score'])
    for i, issue in enumerate(issues):
        issue['priority'] = i + 1

    return issues


# ── Postflop drilldown builder ────────────────────────────────────────

def _build_river_drilldown(river_bet_hands, hbi):
    """Build postflop action drilldown rows from river bet hands."""
    rows = []
    # Group by pot-type + hero-role pattern
    _patterns = defaultdict(list)
    for h in river_bet_hands:
        if not h.get('id'):
            continue
        _pot = '3BP' if h.get('pot_type_3bet') else 'SRP'
        _role = 'PFR IP' if h.get('pfr') and h.get('ip') else (
            'PFR OOP' if h.get('pfr') else (
                'Caller IP' if h.get('ip') else 'Caller OOP'))
        _tex = _classify_board_texture(h.get('board', []))
        _key = (_pot, _role, _tex)
        _patterns[_key].append(h)

    for (pot, role, tex), group in sorted(_patterns.items(), key=lambda x: -len(x[1])):
        if len(group) < 2:
            continue
        _gids = [h['id'] for h in group if h.get('id')]
        rows.append({
            'street': 'river',
            'pot_type': pot,
            'hero_role': role,
            'board_texture': tex,
            'stack_depth': '',
            'spr': None,
            'villain_line': '',
            'hero_action': 'bet',
            'recommended_action': 'check back (review needed)',
            'error_type': 'possible SDV turned into bluff',
            'frequency': len(group),
            'ev_estimate': 'medium',
            'representative_hand_ids': _gids[:3],
            'all_hand_ids': _gids,
            'training': _make_training(
                type_='review', label='Review Hands', status='needs_review',
                hand_ids=_gids[:5], spot_count=len(group),
                description=f'Review {len(group)} river bets as {role} in {pot} on {tex} boards.'),
        })

    return rows


# ── Coverage report ───────────────────────────────────────────────────

def build_coverage_report(stats, rd, hands):
    """Build the opportunity coverage report.

    Shows which poker situations are analyzed vs invisible.
    """
    _eai = stats.get('eai', {}).get('hands', []) or []
    _phids = stats.get('popup_hand_ids', {}) or {}
    _analyst_ids = {h for h, c in (rd.get('analyst_commentary', {}) or {}).items()
                    if isinstance(c, dict) and h.startswith('TM')}

    coverage = [
        {'spot': 'Open/fold preflop',
         'opportunities': sum(1 for h in hands if h.get('first_in')),
         'auto_scored': sum(1 for h in hands if h.get('first_in')),
         'analyst_reviewed': 0, 'has_drill_down': True},
        {'spot': 'BB defend',
         'opportunities': sum(1 for h in hands if h.get('position') == 'BB' and h.get('hero_faced_raise')),
         'auto_scored': sum(1 for h in hands if h.get('position') == 'BB' and h.get('hero_faced_raise')),
         'analyst_reviewed': 0, 'has_drill_down': True},
        {'spot': 'Flop c-bet decision',
         'opportunities': sum(1 for h in hands if h.get('pfr') and len(h.get('board', [])) >= 3),
         'auto_scored': sum(1 for h in hands if h.get('pfr') and len(h.get('board', [])) >= 3),
         'analyst_reviewed': 0, 'has_drill_down': True},
        {'spot': 'Turn barrel decision',
         'opportunities': len(_phids.get('double_barrel_ids', [])) + len(_phids.get('missed_barrel_ids', [])),
         'auto_scored': len(_phids.get('double_barrel_ids', [])) + len(_phids.get('missed_barrel_ids', [])),
         'analyst_reviewed': 0, 'has_drill_down': True},
        {'spot': 'River bet/check',
         'opportunities': sum(1 for h in hands if len(h.get('board', [])) >= 5 and h.get('vpip')),
         'auto_scored': sum(1 for h in hands if len(h.get('board', [])) >= 5 and h.get('vpip')),
         'analyst_reviewed': 0, 'has_drill_down': True},
        {'spot': 'Facing raise/jam',
         'opportunities': sum(1 for h in hands if h.get('hero_faced_raise')),
         'auto_scored': sum(1 for h in hands if h.get('hero_faced_raise')),
         'analyst_reviewed': 0, 'has_drill_down': False},
        {'spot': 'All-in equity',
         'opportunities': sum(1 for h in hands if h.get('pf_allin') or h.get('flop_allin')),
         'auto_scored': len(_eai),
         'analyst_reviewed': sum(1 for e in _eai if e.get('id') in _analyst_ids),
         'has_drill_down': True},
        {'spot': 'Multiway pots',
         'opportunities': sum(1 for h in hands if h.get('players_at_flop', 0) > 2),
         'auto_scored': sum(1 for h in hands if h.get('players_at_flop', 0) > 2),
         'analyst_reviewed': 0, 'has_drill_down': False},
    ]

    return coverage
