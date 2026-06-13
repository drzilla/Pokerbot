"""
gem_drilldown_map.py — Single source of truth for report drill-downs.

Every metric that appears in the report maps to:
  - section: the anchor ID where the detail breakdown lives
  - filter: a string key that collect_hand_ids() resolves to a hand filter
  - group_by: optional field for per-position/per-street breakdown
  - popup_title: template for the hand-list popup title ({pos}, {n} interpolated)

The renderer calls:
  ids = collect_hand_ids(hands, filter_key, group_value)
  link = make_popup(ids, popup_title)

This replaces the per-table hand-ID collection scattered across 14 renderer files.
One place to add a new metric. One place to verify coverage. Zero orphan drill-downs.
"""


# ============================================================
# FILTER REGISTRY — maps filter keys to hand-dict predicates
# ============================================================

def _normalize_hand(cards):
    """Normalize ['Ah','Kd'] → 'AKo' for card-class matching."""
    if not cards or len(cards) < 2:
        return ''
    r1, s1 = cards[0][0], cards[0][1] if len(cards[0]) > 1 else '?'
    r2, s2 = cards[1][0], cards[1][1] if len(cards[1]) > 1 else '?'
    RANK_ORD = '23456789TJQKA'
    if RANK_ORD.index(r1) < RANK_ORD.index(r2):
        r1, r2 = r2, r1
        s1, s2 = s2, s1
    if r1 == r2:
        return r1 + r2
    return r1 + r2 + ('s' if s1 == s2 else 'o')


PREMIUMS = {'AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo'}
STRONG = {'TT', '99', 'AQs', 'AQo', 'AJs', 'KQs'}


def _stack_bucket(stack_bb):
    if stack_bb < 12: return '<12BB'
    if stack_bb < 25: return '12-25BB'
    if stack_bb < 40: return '25-40BB'
    return '40BB+'


# Each filter is: (key, predicate_fn(hand) → bool)
# group_by filters take (hand, group_value) → bool
FILTERS = {}


def _register(key, fn):
    FILTERS[key] = fn


# Position-based
_register('pos',              lambda h, v: h.get('position') == v)
_register('pos_vpip',         lambda h, v: h.get('position') == v and h.get('vpip'))
_register('pos_pfr',          lambda h, v: h.get('position') == v and h.get('pfr'))
_register('pos_limp',         lambda h, v: h.get('position') == v and
                              'limp' in (h.get('pf_action') or ''))

# 3-bet
_register('3bet',             lambda h, v=None: h.get('hero_3bet'))
_register('3bet_vs',          lambda h, v: h.get('hero_3bet') and
                              h.get('opener_position') in _OPENER_BUCKETS.get(v, {v}))
_register('3bet_from',        lambda h, v: h.get('position') == v and h.get('hero_3bet'))

# Squeeze
_register('squeeze',          lambda h, v=None: h.get('is_squeeze'))
_register('squeeze_from',     lambda h, v: h.get('position') == v and h.get('is_squeeze'))

# 4-bet / 5-bet
_register('4bet',             lambda h, v=None: h.get('hero_4bet_only') or
                              h.get('hero_5bet_plus'))
_register('4bet_from',        lambda h, v: h.get('position') == v and
                              (h.get('hero_4bet_only') or h.get('hero_5bet_plus')))
_register('5bet',             lambda h, v=None: h.get('hero_5bet_plus'))

# Cold call
_register('cold_call',        lambda h, v=None: h.get('cold_called'))
_register('cold_call_from',   lambda h, v: h.get('position') == v and h.get('cold_called'))

# Steal / defense
_register('fold_to_steal',    lambda h, v=None: h.get('fold_to_steal_bb'))
_register('faced_steal',      lambda h, v=None: h.get('faced_steal_bb'))
_register('restole',          lambda h, v=None: h.get('restole'))

# Defense matrices
_register('sb_defend_vs',     lambda h, v: h.get('position') == 'SB' and
                              h.get('hero_faced_raise') and h.get('opener_position') == v and
                              (h.get('cold_called') or h.get('hero_3bet')))
_register('sb_fold_vs',       lambda h, v: h.get('position') == 'SB' and
                              h.get('hero_faced_raise') and h.get('opener_position') == v and
                              not h.get('cold_called') and not h.get('hero_3bet'))
_register('bb_defend_vs',     lambda h, v: h.get('position') == 'BB' and
                              h.get('hero_faced_raise') and h.get('opener_position') == v and
                              (h.get('cold_called') or h.get('hero_3bet')))
_register('bb_fold_vs',       lambda h, v: h.get('position') == 'BB' and
                              h.get('hero_faced_raise') and h.get('opener_position') == v and
                              not h.get('cold_called') and not h.get('hero_3bet'))

# Card quality
_register('premium',          lambda h, v=None: _normalize_hand(h.get('cards', [])) in PREMIUMS)
_register('strong',           lambda h, v=None: _normalize_hand(h.get('cards', [])) in STRONG)
_register('suited',           lambda h, v=None: len(h.get('cards', [])) >= 2 and
                              h['cards'][0][1:] == h['cards'][1][1:] if len(h.get('cards',[])) >= 2 else False)
_register('pair',             lambda h, v=None: len(h.get('cards', [])) >= 2 and
                              h['cards'][0][0] == h['cards'][1][0] if len(h.get('cards',[])) >= 2 else False)

# Made hands
_register('made_set',         lambda h, v=None: any(dp.get('class') == 'set'
                              for dp in (h.get('draw_profile') or {}).values()))
_register('made_flush',       lambda h, v=None: any(dp.get('class') == 'flush'
                              for dp in (h.get('draw_profile') or {}).values()))
_register('made_straight',    lambda h, v=None: any(dp.get('class') == 'straight'
                              for dp in (h.get('draw_profile') or {}).values()))

# All-ins by equity bucket
_register('ai_ahead',         lambda h, v=None: h.get('pf_allin') and
                              (h.get('hero_equity') or 0) >= 0.55)
_register('ai_flip',          lambda h, v=None: h.get('pf_allin') and
                              0.42 <= (h.get('hero_equity') or 0) < 0.55)
_register('ai_behind',        lambda h, v=None: h.get('pf_allin') and
                              (h.get('hero_equity') or 0) < 0.42)

# Bluff profile (from stats, not hands — IDs collected in analyzer)
_register('bluff_value',      lambda h, v=None: False)  # placeholder — IDs from stats
_register('bluff_semi',       lambda h, v=None: False)
_register('bluff_pure',       lambda h, v=None: False)

# Stack depth
_register('depth_bucket',     lambda h, v: _stack_bucket(h.get('stack_bb', 0)) == v)

# Tournament
_register('tournament',       lambda h, v: h.get('tournament') == v)

# VPIP hands (for general filtering)
_register('vpip',             lambda h, v=None: h.get('vpip'))
_register('went_to_sd',       lambda h, v=None: h.get('went_to_sd'))

# Opener bucket mapping for 3-bet vs position
_OPENER_BUCKETS = {
    'EP': {'UTG', 'UTG+1', 'UTG+2', 'EP'},
    'MP': {'MP', 'LJ', 'HJ'},
    'LP': {'CO', 'BTN'},
    'Blinds': {'SB', 'BB'},
}


# ============================================================
# METRIC MAP — every report metric → its drill-down config
# ============================================================

METRICS = {
    # S8.1 Position Analysis
    'pos_hands':        {'section': 'sec-8-1', 'filter': 'pos',        'group_by': 'position',
                         'title': '{group} hands ({n})'},
    'pos_vpip':         {'section': 'sec-8-1', 'filter': 'pos_vpip',   'group_by': 'position',
                         'title': '{group} VPIP hands ({n})'},
    'pos_pfr':          {'section': 'sec-8-1', 'filter': 'pos_pfr',    'group_by': 'position',
                         'title': '{group} PFR hands ({n})'},

    # S8.4 3-Bet
    '3bet_vs_ep':       {'section': 'sec-8-4', 'filter': '3bet_vs',    'group_by': 'opener',
                         'title': '3-Bets vs {group} ({n})'},
    '3bet_from':        {'section': 'sec-8-4', 'filter': '3bet_from',  'group_by': 'position',
                         'title': '3-Bets from {group} ({n})'},

    # S8.5 Squeeze
    'squeeze':          {'section': 'sec-8-5', 'filter': 'squeeze',
                         'title': 'Hero Squeezes ({n})'},
    'squeeze_from':     {'section': 'sec-8-5', 'filter': 'squeeze_from', 'group_by': 'position',
                         'title': 'Squeezes from {group} ({n})'},

    # S8.6 4-Bet
    '4bet_from':        {'section': 'sec-8-6', 'filter': '4bet_from',  'group_by': 'position',
                         'title': '4-Bets from {group} ({n})'},

    # S8.3 Defense
    'sb_defend_vs':     {'section': 'sec-8-3', 'filter': 'sb_defend_vs', 'group_by': 'opener',
                         'title': 'SB defends vs {group} ({n})'},
    'sb_fold_vs':       {'section': 'sec-8-3', 'filter': 'sb_fold_vs', 'group_by': 'opener',
                         'title': 'Missed SB defends vs {group} ({n})'},
    'bb_defend_vs':     {'section': 'sec-8-3', 'filter': 'bb_defend_vs', 'group_by': 'opener',
                         'title': 'BB defends vs {group} ({n})'},
    'bb_fold_vs':       {'section': 'sec-8-3', 'filter': 'bb_fold_vs', 'group_by': 'opener',
                         'title': 'Missed BB defends vs {group} ({n})'},

    # S11.9 Steal Defense
    'fold_to_steal':    {'section': 'sec-11-9', 'filter': 'fold_to_steal',
                         'title': 'BB Fold-to-Steal ({n})'},
    'restole':          {'section': 'sec-11-9', 'filter': 'restole',
                         'title': 'Hero Re-Steal ({n})'},

    # S1.5 Card Quality
    'premiums':         {'section': 'sec-1-5', 'filter': 'premium',
                         'title': 'Premium hands ({n})'},
    'strong':           {'section': 'sec-1-5', 'filter': 'strong',
                         'title': 'Strong hands ({n})'},

    # S7.2 Bluff Profile (IDs from stats, not hand filter)
    'bluff_value':      {'section': 'sec-7-2', 'filter': 'bluff_value',
                         'title': 'Value Bets ({n})', 'ids_from_stats': 'bluff_profile.value_ids'},
    'bluff_semi':       {'section': 'sec-7-2', 'filter': 'bluff_semi',
                         'title': 'Semi-Bluffs ({n})', 'ids_from_stats': 'bluff_profile.semi_ids'},
    'bluff_pure':       {'section': 'sec-7-2', 'filter': 'bluff_pure',
                         'title': 'Pure Bluffs ({n})', 'ids_from_stats': 'bluff_profile.pure_ids'},

    # S1.1 Per-Tournament
    'tournament':       {'section': 'sec-1-1', 'filter': 'tournament', 'group_by': 'tournament',
                         'title': '{group} ({n} hands)'},

    # Leak Watchlist metric → section mapping
    'Cold_Call_NB':         {'section': 'sec-8-8'},
    'VPIP_PFR_Gap_Raw':     {'section': 'sec-6-2'},
    'CR_Flop_Pct':          {'section': 'sec-9-3'},
    'AF':                   {'section': 'sec-6-2'},
    'F2_Flop_CBet_Large':   {'section': 'sec-9-1'},
    'F2_Flop_CBet_Small':   {'section': 'sec-9-1'},
    'VPIP':                 {'section': 'sec-6-2'},
    'BB_Iso_SB_Limp':       {'section': 'sec-8-3'},
    'F2_Turn_CBet_Small':   {'section': 'sec-10-1'},
    'River_Bet_Avg_bb':     {'section': 'sec-11-11'},
    'Agg_React_Delta':      {'section': 'sec-6-2'},
    'ATS_Raw':              {'section': 'sec-8-1'},
    'ThreeBet_OOP':         {'section': 'sec-8-5'},
    'Flop_CBet_HU_OOP':     {'section': 'sec-9-1'},
    'CBet_3BP':             {'section': 'sec-9-2'},
    'Triple_Barrel':        {'section': 'sec-11-11'},
    'Pure_Bluff_Pct':       {'section': 'sec-11-11'},
    'Semi_Bluff_Pct':       {'section': 'sec-11-11'},
    'Hero_4Bet':            {'section': 'sec-8-7'},
    'PFR':                  {'section': 'sec-6-2'},
}


# ============================================================
# PUBLIC API — used by renderers
# ============================================================

def collect_hand_ids(hands, filter_key, group_value=None, cap=30):
    """Collect hand IDs matching a filter. Returns list[str]."""
    fn = FILTERS.get(filter_key)
    if not fn:
        return []
    ids = []
    for h in hands:
        if not h.get('id'):
            continue
        try:
            if group_value is not None:
                if fn(h, group_value):
                    ids.append(h['id'])
            else:
                if fn(h):
                    ids.append(h['id'])
        except (TypeError, KeyError, IndexError):
            continue
        if len(ids) >= cap:
            break
    return ids


def collect_from_stats(stats, dotpath, cap=30):
    """Collect hand IDs from a dotpath in stats (e.g. 'bluff_profile.value_ids')."""
    parts = dotpath.split('.')
    obj = stats
    for p in parts:
        if isinstance(obj, dict):
            obj = obj.get(p)
        else:
            return []
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, str)][:cap]
    return []


def make_popup_html(ids, title_template, group_value=None, n=None):
    """Generate a hand-list-trigger <a> tag. Returns HTML string or None."""
    if not ids:
        return None
    _n = n or len(ids)
    title = title_template.replace('{n}', str(_n))
    if group_value:
        title = title.replace('{group}', str(group_value))
    hids_str = ','.join(ids)
    return (f'<a class="hand-list-trigger" href="#" '
            f'data-hids="{hids_str}" '
            f'data-list-title="{title}">')


def section_link(metric_key):
    """Return the section anchor for a metric, or None."""
    m = METRICS.get(metric_key)
    return m.get('section') if m else None


def metric_popup(hands, stats, metric_key, group_value=None, display_text=None, n=None):
    """One-call: collect IDs + wrap in popup HTML. Returns display_text wrapped
    in a hand-list-trigger link, or plain display_text if no IDs found."""
    m = METRICS.get(metric_key)
    if not m:
        return display_text or ''
    # Try stats-based IDs first
    ids_path = m.get('ids_from_stats')
    if ids_path:
        ids = collect_from_stats(stats, ids_path)
    else:
        filter_key = m.get('filter', '')
        ids = collect_hand_ids(hands, filter_key, group_value)
    if not ids:
        return display_text or ''
    _n = n or len(ids)
    title = m.get('title', f'{metric_key} ({_n})')
    title = title.replace('{n}', str(_n))
    if group_value:
        title = title.replace('{group}', str(group_value))
    hids_str = ','.join(ids)
    dt = display_text or str(_n)
    return (f'<a class="hand-list-trigger" href="#" '
            f'data-hids="{hids_str}" '
            f'data-list-title="{title}">{dt}</a>')
