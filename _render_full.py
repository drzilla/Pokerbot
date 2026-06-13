#!/usr/bin/env python3
"""Generate _test_rendered.html with rich test data exercising all v3 sections."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_content_parity import _enriched_fixture, _setup_state
from gem_report_draft.draft import render_html
from gem_report_draft import _state

s, rd, h = _enriched_fixture()

# ── S1.4 All-Ins ──────────────────────────────────────────────────
s.setdefault('eai', {}).update({
    'total': 10,
    'preflop': {
        'ahead':  {'pct': 82.0, 'count': 3, 'won': 2},
        'flip':   {'pct': 52.0, 'count': 2, 'won': 1},
        'behind': {'pct': 18.0, 'count': 1, 'won': 0},
    },
    'postflop': {
        'ahead':  {'pct': 88.0, 'count': 2, 'won': 2},
        'flip':   {'pct': 48.0, 'count': 2, 'won': 0},
        'behind': {'pct': 22.0, 'count': 1, 'won': 1},
    },
})
s['eai_ev_adjusted'] = {
    'preflop':  {'actual_win_pct': 50.0, 'expected_win_pct': 54.0,
                 'delta_wins': -0.5, 'actual_wins': 3.0, 'total_spots': 6,
                 'expected_wins': 3.5},
    'postflop': {'actual_win_pct': 60.0, 'expected_win_pct': 55.0,
                 'delta_wins': 0.6, 'actual_wins': 3.0, 'total_spots': 5,
                 'expected_wins': 2.4},
    'approx_bb_variance_pf': -3.2,
    'approx_bb_variance_post': 4.1,
}
s['suckouts'] = {
    'against_hero': [
        {'id': 'TM10000001', 'hero': 'Ah Kd', 'villain': 'Jh Ts',
         'board': 'Ks 7c 2d Th 3s', 'hero_equity': 0.72,
         'street': 'river', 'tournament': 'Test', 'date': '2026-05-27'}
    ],
    'by_hero': [],
}

# ── S1.5 Card Quality ────────────────────────────────────────────
s.setdefault('card_quality', {}).update({
    'premium_pct': 8.5, 'premium_expected': 6.0, 'premium_n': 200,
    'pairs_pct': 12.0, 'strong_pct': 15.0, 'suited_pct': 24.0,
    'aces_pct': 15.0,
})
s['_card_quality_detail'] = {
    'premium': {'dealt': 17, 'expected': 12, 'delta': 5, 'ci': (5.5, 12.0)},
    'strong':  {'dealt': 30, 'expected': 28, 'delta': 2, 'ci': (12.0, 19.0)},
    'pairs':   {'dealt': 24, 'expected': 24, 'delta': 0, 'ci': (8.0, 16.0)},
    'suited':  {'dealt': 48, 'expected': 47, 'delta': 1, 'ci': (20.0, 28.0)},
    'aces':    {'dealt': 30, 'expected': 30, 'delta': 0, 'ci': (12.0, 18.0)},
    'good_hands_pct': 32.0, 'good_hands_expected': 30.0,
    'good_hands_ci': (28.0, 36.0), 'good_hands_n': 200,
}

# ── S1.6 Made Hands vs Expected ──────────────────────────────────
s['_made_hands'] = {}
for cls, r, e, t, v in [
    ('set', 15.0, 12.0, 12.0, '\U0001f7e2'),
    ('flush', 8.0, 6.5, 6.5, '\U0001f7e2'),
    ('straight', 5.0, 4.0, 4.0, '\U0001f7e1'),
    ('two_pair', 18.0, 15.0, 15.0, '\U0001f7e2'),
    ('full_house', 3.0, 2.5, 2.5, '⚪'),
]:
    s['_made_hands'][cls] = {
        'rate': r, 'ci': (r - 5, r + 5), 'target': (t - 5, t + 5),
        'expected': e, 'opp': 50, 'made': int(r * 50 / 100),
        'verdict': v, 'opp_label': 'flops seen',
        'texture_dist': {'dry_low': 3, 'paired_low': 2},
    }

# ── S1.9 Intra-Session Arc ───────────────────────────────────────
s['intra_session_arc'] = {
    'quartiles': [
        # B220: cev_per_100 is a fraction of starting stack (same units as
        # cev_session.cev_per_stack_per_100). Renderer multiplies by 100 for
        # display: 0.008 → +0.8%, -0.021 → -2.1%.
        {'quartile': 1, 'n_hands': 50, 'vpip': 22.0, 'mistakes_per_100': 0.5,
         'bb_per_100': 15.0, 'cev_per_100': 0.008,
         'first_time': '19:00', 'last_time': '19:45'},
        {'quartile': 2, 'n_hands': 50, 'vpip': 25.0, 'mistakes_per_100': 1.2,
         'bb_per_100': -5.0, 'cev_per_100': -0.003,
         'first_time': '19:45', 'last_time': '20:30'},
        {'quartile': 3, 'n_hands': 50, 'vpip': 28.0, 'mistakes_per_100': 1.8,
         'bb_per_100': -20.0, 'cev_per_100': -0.012,
         'first_time': '20:30', 'last_time': '21:15'},
        {'quartile': 4, 'n_hands': 50, 'vpip': 30.0, 'mistakes_per_100': 2.5,
         'bb_per_100': -35.0, 'cev_per_100': -0.021,
         'first_time': '21:15', 'last_time': '22:00'},
    ],
    'tilt_flag': True,
    'tilt_note': 'Q4 mistake rate 5x Q1 — fatigue pattern.',
}

# ── S13.1 Population Deviations ──────────────────────────────────
s['postflop_deviations_v732'] = [
    {'rule': 'detector_fold_to_cbet_by_pos', 'pos': 'CO',
     'pct': 72.0, 'n': 5, 'target': '45-55', 'delta_pp': 22.0,
     'confidence': '🟡 low-n'},
    {'rule': 'detector_call_cbet_by_pos', 'pos': 'BTN',
     'pct': 28.0, 'n': 7, 'target': '40-50', 'delta_pp': -17.0,
     'confidence': '🟡 low-n'},
]

# ── S1.2 Top P&L Lines (filter <5, sort BB/h desc) ───────────────
s['top_losing_lines'] = [
    {'line': 'AKo UTG open → 3bet pot', 'count': 8,
     'net_bb': -45.0, 'avg_bb': -5.6, 'confidence': '\U0001f7e1'},
    {'line': 'KQs CO open → call 3bet', 'count': 6,
     'net_bb': -30.0, 'avg_bb': -5.0, 'confidence': '\U0001f7e1'},
    {'line': '77 BTN call → set mine', 'count': 3,
     'net_bb': -9.0, 'avg_bb': -3.0, 'confidence': '⚪'},
    {'line': 'A5s SB open → fold to 3bet', 'count': 4,
     'net_bb': -12.0, 'avg_bb': -3.0, 'confidence': '⚪'},
]
s['top_winning_lines'] = [
    {'line': 'QQ+ cold 4bet', 'count': 5,
     'net_bb': 60.0, 'avg_bb': 12.0, 'confidence': '\U0001f7e2'},
    {'line': 'AJs BTN steal', 'count': 7,
     'net_bb': 21.0, 'avg_bb': 3.0, 'confidence': '\U0001f7e2'},
]

# ── S1.1a Result Attribution ──────────────────────────────────────
rd['results_attribution'] = {
    'n_hands': 200, 'surface_bb_per_100': -2.5,
    'card_quality_var_bb': 1.5, 'card_quality_delta_pp': 2.1,
    'card_quality_var_per_100': 0.8,
    'made_hands_var_bb': -1.0, 'made_hands_var_per_100': -0.5,
    'cooler_var_bb': -2.0, 'cooler_count_actual': 3,
    'cooler_count_expected': 1.5, 'cooler_var_per_100': -1.0,
    'eai_variance_bb': -1.8, 'eai_variance_per_100': -0.9,
    'non_tail_mistake_count': 4, 'non_tail_mistake_per_100': -1.5,
    'non_tail_mistake_cev_per_100': -0.012,
    'tail_fold_count': 2, 'tail_fold_per_100': -0.3,
    'tail_fold_cev_per_100': -0.003,
    'implied_true_ev_extended_per_100': 1.4,
    'implied_ceiling_extended_per_100': 2.9,
    'implied_true_ev_cev_per_100': 0.014,
    'implied_ceiling_cev_per_100': 0.029,
    'surface_cev_per_100': -0.025,
}
rd['variance_cev'] = {
    'card_quality': {'cev_per_100': 0.008},
    'made_hands':   {'cev_per_100': -0.005},
    'cooler':       {'cev_per_100': -0.010},
    'eai':          {'cev_per_100': -0.009},
}
rd['cev_session'] = {
    'cev_per_stack_total': -0.05, 'cev_per_stack_per_100': -0.025,
    'net_chips_total': -500, 'n_resolved': 1, 'n_unresolved': 0,
}

# ── S8.1 Positions + Stack Depth ─────────────────────────────────
s['positions'] = {
    'BTN': {'hands': 35, 'vpip_pct': 32.0, 'pfr_pct': 28.0, 'net_bb': 15.0,
            'bb_per_100': 42.9, 'fi': 20,
            'vpip_net_bb': 12.0, 'vpip_bb_per_hand': 1.1},
    'CO':  {'hands': 30, 'vpip_pct': 25.0, 'pfr_pct': 22.0, 'net_bb': -8.0,
            'bb_per_100': -26.7, 'fi': 18,
            'vpip_net_bb': -5.0, 'vpip_bb_per_hand': -0.7},
    'HJ':  {'hands': 28, 'vpip_pct': 18.0, 'pfr_pct': 16.0, 'net_bb': 3.0,
            'bb_per_100': 10.7, 'fi': 15,
            'vpip_net_bb': 2.0, 'vpip_bb_per_hand': 0.4},
    'SB':  {'hands': 25, 'vpip_pct': 28.0, 'pfr_pct': 20.0, 'net_bb': -12.0,
            'bb_per_100': -48.0, 'fi': 10,
            'vpip_net_bb': -8.0, 'vpip_bb_per_hand': -1.1},
    'BB':  {'hands': 25, 'vpip_pct': 35.0, 'pfr_pct': 10.0, 'net_bb': -5.0,
            'bb_per_100': -20.0, 'fi': 5,
            'vpip_net_bb': -3.0, 'vpip_bb_per_hand': -0.3},
}
s['stack_depth'] = {
    '0-8BB':   {'hands': 15, 'vpip': 40.0, 'pfr': 35.0,
                'nb_hands': 10, 'nb_vpip': 45.0, 'nb_pfr': 40.0, 'nb_gap': 5.0},
    '8-25BB':  {'hands': 60, 'vpip': 25.0, 'pfr': 20.0,
                'nb_hands': 40, 'nb_vpip': 28.0, 'nb_pfr': 22.0, 'nb_gap': 6.0},
    '25-40BB': {'hands': 80, 'vpip': 22.0, 'pfr': 18.0,
                'nb_hands': 55, 'nb_vpip': 24.0, 'nb_pfr': 20.0, 'nb_gap': 4.0},
    '>40BB':   {'hands': 45, 'vpip': 20.0, 'pfr': 17.0,
                'nb_hands': 30, 'nb_vpip': 22.0, 'nb_pfr': 19.0, 'nb_gap': 3.0},
}

# ── S8.3 Blind Combat ────────────────────────────────────────────
s['facing_action'] = {
    'sb_defense_vs_lp': {'rate': 35.0, 'opps': 20, 'defends': 7,
                         'call': 4, 'call_pct': 20.0,
                         'three_bet': 3, 'three_bet_pct': 15.0},
    'bb_defense_vs_steal': {'rate': 60.0, 'opps': 30, 'defends': 18,
                            'call': 12, 'call_pct': 40.0,
                            'three_bet': 6, 'three_bet_pct': 20.0},
    'bb_defense_vs_nonsteal': {'rate': 45.0, 'opps': 15, 'defends': 7,
                               'call': 5, 'call_pct': 33.3,
                               'three_bet': 2, 'three_bet_pct': 13.3},
}

# ── Coolers for S1.7 ─────────────────────────────────────────────
s['coolers'] = {
    'hands': [
        {'id': 'TM10000001', 'type': 'set_over_set',
         'hero_hand': 'Ah Kd', 'villain_hand': 'Jh Ts',
         'board': 'Ks 7c 2d Th 3s', 'net_bb': -45.0,
         'tournament': 'Test', 'date': '2026-05-27'},
    ],
    'positive': [],
}

# ── Opening Dashboard data ───────────────────────────────────────

# Analyst commentary (from session_analysis_20260528-29.json)
rd['analyst_commentary'] = {
    'TM6011729390': {
        'verdict': 'III.2',
        'hand_strength': 'QQ → underpair (Ad on turn)',
        'argument': '**TL;DR:** Cbet-jamming 60BB with QQ on a turned A is -EV.',
    },
    'TM6011731737': {
        'verdict': 'III.3',
        'hand_strength': 'TPTK (A-high, top kicker)',
        'argument': '**TL;DR:** Standard TPTK barrel in a 3BP. Cleared.',
    },
    'TM6010776935': {
        'verdict': 'III.3',
        'hand_strength': 'TPTK (A-high, Q kicker)',
        'argument': '**TL;DR:** TPTK x-back-then-bet is fine vs capped BB. Cleared.',
    },
    'TM6011597113': {
        'verdict': 'III.3',
        'hand_strength': 'A-high + nut-flush draw → nut flush',
        'argument': '**TL;DR:** Nut flush on turn. Textbook, not a leak.',
    },
    'TM6010775742': {
        'verdict': 'III.2',
        'hand_strength': 'A-high (busted NFD; AhKh)',
        'argument': '**TL;DR:** Check flop → barrel turn → fold river is the one-and-done pattern.',
    },
    'TM6012213481': {
        'verdict': 'III.2',
        'hand_strength': 'busted gutshot/flush-draw air (Td9d)',
        'argument': '**TL;DR:** Barrelling air multiway into K-A-paired board is the leak.',
    },
    'TM6011975747': {
        'verdict': 'III.3',
        'hand_strength': 'TPGK busted → river bluff-jam',
        'argument': '**TL;DR:** River jam with the right blockers is defensible. Cleared.',
    },
    'TM6011658306': {
        'verdict': 'III.3',
        'hand_strength': 'A4o SB open-jam blind-vs-blind, FT zone',
        'argument': '**TL;DR:** A4o open-jam at 33BB in FT zone is standard. Cleared.',
    },
    'TM6011732892': {
        'verdict': 'I.7',
        'hand_strength': 'KK → ran into hands/board, lost 35BB',
        'argument': '**TL;DR:** KK stack-off on Q-Q-2-T-A. Cooler, not a leak.',
    },
    '__synthesis__': {
        'leaks': {
            # Item 6: deviation judgments keyed by "Rule_label Position"
            'Fold to cbet CO': {
                'judgment': 'Noise — 3/5 were correct folds on dry boards vs strong c-bets.',
                'real_or_noise': 'noise',
            },
            'Call cbet BTN': {
                'judgment': 'Mixed — two passive flats missed value; one was a correct peel.',
                'real_or_noise': 'mixed',
            },
            'one_and_done_multiway_barrel': {
                'judgment': 'Two confirmed III.2 barrels: AhKh (-18BB) and Td9d (-13BB). Same pattern: skip flop, fire turn with no made hand, abandon river. Recurrence of the one-and-done barrel leak. Direction: bet the flop when equity is highest, or give up turn.',
                'real_or_noise': 'real',
                'bb_per_100_est': -2.8,
                'examples': [
                    {'hand_id': 'TM6010775742'},
                    {'hand_id': 'TM6012213481'},
                ],
            },
            'qq_value_to_bluff_conversion': {
                'judgment': 'One III.2: QQ cbet-jammed 60BB on turned A (~11% equity). Showdown-value hand turned into bluff. Won the pot but EV-negative.',
                'real_or_noise': 'real',
                'bb_per_100_est': -0.9,
                'examples': [
                    {'hand_id': 'TM6011729390'},
                ],
            },
        },
        'session_interpretation': {
            'read': 'This was a solid session with a few identifiable strategic leaks. True EV was positive despite the surface result being dragged by variance. The main work is the one-and-done barrel pattern — a fixable, repeatable spot.',
            'attribution_guide': 'Card quality ran slightly hot, all-ins ran cold, made hands and coolers both slightly negative. The net variance was mildly negative, meaning the actual result undersells the quality of play.',
        },
        'headline': 'Solid play, mild variance drag',
        'session_read': 'The session featured 200 hands across 15 tournaments with 17 bullets. Hero played a clean session with zero punts, but three strategic leaks (III.2) surfaced in the analyst review. The dominant pattern is the one-and-done multiway barrel: checking flop, betting turn with air, then folding river. This pattern cost approximately 2.8 BB/100. The QQ spot is a separate single-instance leak worth drilling.',
    },
}

# Add total_outcome_variance_per_100 to results_attribution
rd['results_attribution']['total_outcome_variance_per_100'] = (
    rd['results_attribution']['card_quality_var_per_100'] +
    rd['results_attribution']['made_hands_var_per_100'] +
    rd['results_attribution']['cooler_var_per_100'] +
    rd['results_attribution']['eai_variance_per_100']
)

# Discipline tier for dashboard
rd['discipline_tier'] = {
    'label': 'Solid', 'emoji': '🟢', 'one_liner': 'Zero punts, 3 strategic leaks',
    'detail': 'No blowup hands. Leaks are pattern-based, not tilt-based.',
    'confirmed_mistakes_count': 3, 'confirmed_mistakes_per_100': 1.5,
}

# Skill band
rd['skill_band'] = {
    'label': 'Winning regular', 'emoji': '🟢', 'ci_width': 71,
}

# Core metrics
s.setdefault('core', {}).update({
    'bb_per_100': 6.0,
    'ev_bb_per_100': 8.2,
})
s.setdefault('csv_row', {}).update({
    'BB_per_100': 6.0,
    'EV_BB_per_100': 8.2,
})
rd['avg_buyin'] = 47
rd['total_invested'] = 796

# USD overlay
rd['usd_overlay'] = {
    'hh_intersect_totals': {
        'total_net': 185, 'roi_pct': 23.2, 'total_cost': 796,
        'n_tournaments': 15, 'n_bullets': 17,
        'top3_cost_share': 0.35, 'biggest_loss_usd': -120,
        'biggest_loss_tournament': 'GGMasters Bounty $44',
    },
    'per_tournament': [
        {'start_date': '2026-05-26', 'tournament_name': 'GGMasters Bounty $44',
         'cost': 44, 'cash_total': 0,   'bullets': 1, 'place': 89,
         'total_players': 200, 'itm': False, 'is_sat': False},
        {'start_date': '2026-05-26', 'tournament_name': 'GGMasters HR $150',
         'cost': 150, 'cash_total': 380, 'bullets': 1, 'place': 3,
         'total_players': 85, 'itm': True, 'is_sat': False},
        {'start_date': '2026-05-26', 'tournament_name': 'Bounty Hunters $33',
         'cost': 33, 'cash_total': 0,   'bullets': 2, 'place': 145,
         'total_players': 300, 'itm': False, 'is_sat': False},
        {'start_date': '2026-05-26', 'tournament_name': 'Daily Main $22',
         'cost': 22, 'cash_total': 55,  'bullets': 1, 'place': 12,
         'total_players': 400, 'itm': True, 'is_sat': False},
        {'start_date': '2026-05-27', 'tournament_name': 'GGMasters Bounty $44',
         'cost': 44, 'cash_total': 0,   'bullets': 1, 'place': 102,
         'total_players': 220, 'itm': False, 'is_sat': False},
        {'start_date': '2026-05-27', 'tournament_name': 'Mystery Bounty $55',
         'cost': 55, 'cash_total': 210, 'bullets': 2, 'place': 5,
         'total_players': 180, 'itm': True, 'is_sat': False},
        {'start_date': '2026-05-27', 'tournament_name': 'Daily Main $22',
         'cost': 22, 'cash_total': 0,   'bullets': 1, 'place': 78,
         'total_players': 350, 'itm': False, 'is_sat': False},
    ],
}

# Leak watchlist (for coach watchlist card)
rd['leak_watchlist'] = {
    'verdict_line': '3 red / 2 amber / 15 green across 20 metrics',
    'top_actions': [
        {'metric': 'BTN open rate', 'value': '28%', 'arrow': '↓',
         'action': 'Open wider from BTN (target 32-36%)', 'status': 'red'},
        {'metric': 'Caller IP aggression', 'value': '42%', 'arrow': '↓',
         'action': 'Stab more when checked to IP (target 55%)', 'status': 'red'},
        {'metric': 'SB pot-entry', 'value': '22%', 'arrow': '↓',
         'action': 'Defend/3-bet more vs CO/BTN opens', 'status': 'amber'},
    ],
    'session_metrics': [],
}

# Drill script
rd['drill_script'] = [
    'When IP villain checks flop to me, bet small 33-50% by default.',
    'Versus CO/BTN open from SB, my call + 3-bet rate should be 30-40%.',
    'When a flat-caller raises turn, default to bluff-catcher zone.',
    'Name the population frequency being exploited before any non-standard river action.',
    'For bust hands, review the 1-2 decisions before the all-in, not the showdown card.',
]

# ── Render ────────────────────────────────────────────────────────
_setup_state(s)
html = render_html(s, rd, h)

out_path = os.path.join(os.path.dirname(__file__), '_test_rendered.html')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"Wrote {len(html):,} chars to {out_path}")
