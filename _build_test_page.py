#!/usr/bin/env python3
"""Build GTOW URL validation test page."""
import html as html_mod
from urllib.parse import urlparse, parse_qs
from gem_gtow import build_gtow_schema, snap_depth, _pick_stacks, CHIPEV_GAMETYPES, _DEPTH_GRIDS

test_cases = []

# Group 1: Per-gametype depth edges
for ts in [3, 5, 6, 7, 8, 9]:
    gt = CHIPEV_GAMETYPES[ts]
    grid = _DEPTH_GRIDS[gt]
    for label, eff in [('min', grid[0]), ('mid', grid[len(grid)//2]), ('max', grid[-1])]:
        pf = ['BTN(H):raises', 'SB:folds', 'BB:calls']
        hand = {
            'id': f'TEST_{ts}max_{label}', 'table_size': ts, 'stack_bb': eff,
            'eff_stack_bb': eff, 'board': ['Ah', '7d', '2s'], 'cards': ['Kh', 'Kd'],
            'position': 'BTN', 'pf_sequence': pf, 'players_at_flop': 2,
        }
        schema = build_gtow_schema(hand)
        test_cases.append({
            'group': f'{ts}-max depth edges',
            'id': f'{ts}max-{label}-{eff}bb',
            'expect': f'{ts}-max ChipEV at {eff}bb, flop Ah7d2s, BTN vs BB',
            'url': schema['url'],
            'status': schema['status'],
        })

# Group 2: Stacks matching (equal stacks, different depths)
for eff in [10, 20, 50, 100]:
    stacks = _pick_stacks('MTTGeneral_8m', eff, 8)
    pf = (['UTG(H):raises'] +
          [f'{p}:folds' for p in ['UTG+1', 'MP', 'HJ', 'CO', 'BTN', 'SB']] +
          ['BB:calls'])
    hand = {
        'id': f'TEST_stacks_{eff}bb', 'table_size': 8, 'stack_bb': eff,
        'eff_stack_bb': eff, 'board': ['Ks', '9c', 'Js'], 'cards': ['Ac', 'Kc'],
        'position': 'UTG', 'pf_sequence': pf, 'players_at_flop': 2,
    }
    schema = build_gtow_schema(hand)
    stacks_short = (stacks or 'none')[:50]
    test_cases.append({
        'group': '8-max stacks matching',
        'id': f'8max-{eff}bb-equal-stacks',
        'expect': f'8-max {eff}bb, stacks={stacks_short}, UTG vs BB, flop Ks9cJs',
        'url': schema['url'],
        'status': schema['status'],
    })

# Group 3: Asymmetric stacks with seat data
app_det = {
    'seats': [
        {'position': 'UTG', 'stack_bb': 30},
        {'position': 'UTG+1', 'stack_bb': 45},
        {'position': 'MP', 'stack_bb': 60},
        {'position': 'HJ', 'stack_bb': 15},
        {'position': 'CO', 'stack_bb': 80},
        {'position': 'BTN', 'stack_bb': 25},
        {'position': 'SB', 'stack_bb': 50},
        {'position': 'BB', 'stack_bb': 35},
    ],
}
pf = (['UTG(H):raises'] +
      [f'{p}:folds' for p in ['UTG+1', 'MP', 'HJ', 'CO', 'BTN', 'SB']] +
      ['BB:calls'])
hand = {
    'id': 'TEST_asym', 'table_size': 8, 'stack_bb': 30, 'eff_stack_bb': 30,
    'board': ['Td', '5h', '2c'], 'cards': ['Ah', 'Ad'],
    'position': 'UTG', 'pf_sequence': pf, 'players_at_flop': 2,
}
schema = build_gtow_schema(hand, app_details=app_det)
stacks_val = parse_qs(urlparse(schema['url']).query).get('stacks', [''])[0]
test_cases.append({
    'group': 'Asymmetric stacks (seat-matched)',
    'id': '8max-30bb-asymmetric',
    'expect': f'8-max 30bb ASYMMETRIC stacks={stacks_val}, UTG vs BB, flop Td5h2c',
    'url': schema['url'],
    'status': schema['status'],
})

# Group 4: Preflop decision points
for ts, pos, pf_seq in [
    (8, 'CO', ['UTG:folds', 'UTG+1:folds', 'MP:folds', 'HJ:folds',
               'CO(H):raises', 'BTN:folds', 'SB:folds', 'BB:folds']),
    (6, 'BTN', ['UTG:folds', 'MP:folds', 'CO:folds',
                'BTN(H):raises', 'SB:folds', 'BB:folds']),
    (9, 'BTN', ['UTG:folds', 'UTG+1:folds', 'UTG+2:folds', 'MP:folds',
                'HJ:folds', 'CO:folds', 'BTN(H):raises', 'SB:folds', 'BB:folds']),
]:
    hand = {
        'id': f'TEST_pf_{ts}max', 'table_size': ts, 'stack_bb': 25,
        'eff_stack_bb': 25, 'board': [], 'cards': ['Ah', 'Ks'],
        'position': pos, 'pf_sequence': pf_seq, 'players_at_flop': 0,
    }
    schema = build_gtow_schema(hand)
    test_cases.append({
        'group': 'Preflop decision points',
        'id': f'{ts}max-preflop-{pos}-25bb',
        'expect': f'{ts}-max 25bb, PF open from {pos}, folds to hero',
        'url': schema['url'],
        'status': schema['status'],
    })

# Group 5: 3-bet pot
pf_3bet = ['UTG:raises', 'UTG+1:folds', 'MP:folds', 'HJ(H):raises',
           'CO:folds', 'BTN:folds', 'SB:folds', 'BB:folds', 'UTG:calls']
hand = {
    'id': 'TEST_3bet', 'table_size': 8, 'stack_bb': 50, 'eff_stack_bb': 50,
    'board': ['Td', '5h', '2c'], 'cards': ['Qh', 'Qd'],
    'position': 'HJ', 'pf_sequence': pf_3bet, 'players_at_flop': 2,
}
schema = build_gtow_schema(hand)
test_cases.append({
    'group': '3-bet pot',
    'id': '8max-3bet-HJvsUTG-50bb',
    'expect': '8-max 50bb, HJ 3-bets UTG, UTG calls, flop Td5h2c',
    'url': schema['url'],
    'status': schema['status'],
})

# Group 6: Fallback (4-way)
hand = {
    'id': 'TEST_4way', 'table_size': 8, 'stack_bb': 30, 'eff_stack_bb': 30,
    'board': ['Ah', '7d', '2s'], 'cards': ['Kh', 'Kd'],
    'position': 'UTG',
    'pf_sequence': ['UTG(H):raises', 'UTG+1:calls', 'MP:calls', 'HJ:folds',
                    'CO:folds', 'BTN:folds', 'SB:folds', 'BB:calls'],
    'players_at_flop': 4,
}
schema = build_gtow_schema(hand)
test_cases.append({
    'group': 'Fallback',
    'id': '8max-4way-30bb',
    'expect': '4-way pot -> falls back to preflop root (no GTOW postflop tree)',
    'url': schema['url'],
    'status': schema['status'],
})

# Build HTML
lines = []
lines.append('<!DOCTYPE html>')
lines.append('<html><head><meta charset="utf-8">')
lines.append('<title>GTOW URL Validation</title>')
lines.append('<style>')
lines.append('body{font-family:system-ui;max-width:1200px;margin:40px auto;padding:0 20px;background:#1a1a2e;color:#e0e0e0}')
lines.append('h1{color:#f0c040}')
lines.append('h2{color:#60b0ff;margin-top:30px;border-top:1px solid #333;padding-top:15px}')
lines.append('.tc{background:#252545;border-radius:8px;padding:16px;margin:12px 0;border-left:4px solid #60b0ff}')
lines.append('.tc.partial{border-left-color:#f0a030}')
lines.append('.id{font-weight:bold;color:#f0c040;font-size:14px}')
lines.append('.expect{color:#a0a0c0;font-size:13px;margin:4px 0}')
lines.append('a{color:#60d060;font-size:12px;word-break:break-all}')
lines.append('.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold}')
lines.append('.badge.ready{background:#204020;color:#60d060}')
lines.append('.badge.partial{background:#403020;color:#f0a030}')
lines.append('.check{margin-top:8px;font-size:12px;color:#808090}')
lines.append('.check label{display:block;padding:2px 0;cursor:pointer}')
lines.append('</style></head><body>')
lines.append('<h1>GTOW URL Validation &mdash; Test Page</h1>')
lines.append('<p>Click each link &rarr; verify GTOW loads the correct solution. Check boxes to track.</p>')
lines.append('<p><b>Verify:</b> (1) No error page (2) Correct gametype (3) Correct depth (4) Stacks shown match (5) Board correct (6) Action tree position correct</p>')

current_group = ''
for i, tc in enumerate(test_cases, 1):
    if tc['group'] != current_group:
        current_group = tc['group']
        lines.append(f'<h2>{html_mod.escape(current_group)}</h2>')
    cls = 'tc partial' if tc['status'] == 'partial' else 'tc'
    esc_url = html_mod.escape(tc['url'] or '')
    url_short = html_mod.escape((tc['url'] or '')[:160])
    lines.append(f'<div class="{cls}">')
    lines.append(f'  <span class="badge {tc["status"]}">{tc["status"]}</span>')
    lines.append(f'  <span class="id">#{i} {html_mod.escape(tc["id"])}</span>')
    lines.append(f'  <div class="expect">{html_mod.escape(tc["expect"])}</div>')
    lines.append(f'  <a href="{esc_url}" target="_blank">{url_short}...</a>')
    lines.append(f'  <div class="check">')
    lines.append(f'    <label><input type="checkbox"> Loads without error</label>')
    lines.append(f'    <label><input type="checkbox"> Correct gametype/depth</label>')
    lines.append(f'    <label><input type="checkbox"> Stacks shown match URL</label>')
    lines.append(f'  </div>')
    lines.append(f'</div>')

lines.append('</body></html>')

with open('_gtow_test_page.html', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'Wrote _gtow_test_page.html with {len(test_cases)} test cases')
