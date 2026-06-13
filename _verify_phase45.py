#!/usr/bin/env python3
"""Phase 4.5 verification script — NOT production code.

Answers the 6 review questions. Run with: python -X utf8 _verify_phase45.py
"""
import re
import sys
import json

sys.path.insert(0, '.')
from test_content_parity import _minimal_fixture, _setup_state
from gem_report_draft.draft import _build
from gem_report_draft import _state

# ============================================================
# Build an enriched fixture that triggers XIV.A + XIV.B
# ============================================================

s, rd, hands = _minimal_fixture()
rd['analyst_commentary'] = {
    'TM10000001': {'argument': 'Good raise.', 'key_decision': 'sizing',
                   'spot': 'BTN open'},
    'TM10000002': {'argument': 'Missed value.', 'key_decision': 'turn check',
                   'spot': 'CO flat'},
}
rd['appendix_hand_details'] = {}
for hid in ['TM10000001', 'TM10000002']:
    rd['appendix_hand_details'][hid] = {
        'bb_size_chips': 100, 'is_bounty': False,
        'seats': [
            {'seat': 1, 'name': 'Hero', 'stack_chips': 5000, 'stack_bb': 50,
             'position': 'BTN', 'is_hero': True,
             'covers_hero': False, 'hero_covers': False},
            {'seat': 2, 'name': 'P1', 'stack_chips': 4500, 'stack_bb': 45,
             'position': 'BB', 'is_hero': False,
             'covers_hero': False, 'hero_covers': True},
        ],
        'actions': {
            'preflop': [
                {'name': 'Hero', 'position': 'BTN', 'action': 'raises',
                 'amount_bb': 2.5, 'all_in': False, 'is_hero': True,
                 'stack_bb': 50},
                {'name': 'P1', 'position': 'BB', 'action': 'calls',
                 'amount_bb': 2.5, 'all_in': False, 'is_hero': False,
                 'stack_bb': 45},
            ],
            'flop': [
                {'name': 'P1', 'position': 'BB', 'action': 'checks',
                 'amount_bb': 0, 'all_in': False, 'is_hero': False,
                 'stack_bb': 45},
                {'name': 'Hero', 'position': 'BTN', 'action': 'bets',
                 'amount_bb': 3, 'all_in': False, 'is_hero': True,
                 'stack_bb': 50},
                {'name': 'P1', 'position': 'BB', 'action': 'calls',
                 'amount_bb': 3, 'all_in': False, 'is_hero': False,
                 'stack_bb': 45},
            ],
            'turn': [], 'river': [],
        },
        'showdown': {},
    }

doc = _build(s, rd, hands)
html = doc.render_html()

print("=" * 60)
print("Q1: ONE-HAND INVARIANT PROOF")
print("=" * 60)

# Count hand-detail-card articles
card_pattern = re.compile(
    r'<article\s+class=.hand-detail-card.\s+data-hand-id=.([^\'\"]+)')
cards = card_pattern.findall(html)
print(f"  hand-detail-card articles: {len(cards)}")
for c in cards:
    print(f"    data-hand-id: {c}")

# Verify each card has no nested <article
body_start = html.find('<body')
body_html = html[body_start:] if body_start >= 0 else html
for m in card_pattern.finditer(body_html):
    hid = m.group(1)
    start = m.start()
    close = body_html.find('</article>', start)
    if close < 0:
        print(f"  FAIL: card {hid} has no closing </article>")
        continue
    snippet = body_html[start + len(m.group(0)):close]
    nested = snippet.count('<article')
    print(f"    card {hid}: closes at +{close - start} chars, nested <article inside: {nested}")

# Verify openHand JS clones ONE card
modal_idx = html.find('function openHand')
if modal_idx >= 0:
    js = html[modal_idx:modal_idx + 500]
    print(f"  openHand JS found:")
    print(f"    uses querySelector (single): {'querySelector(' in js}")
    print(f"    uses cloneNode(true): {'cloneNode(true)' in js}")
    print(f"    references siblings: {'ibling' in js}")
    print(f"    references handSiblingNodes: {'handSiblingNodes' in js}")
else:
    print("  FAIL: openHand function not found in HTML")

print()
print("=" * 60)
print("Q2: CI-TOOLTIP INTACT")
print("=" * 60)

# Count CI column headers
ci_th = re.findall(r'<th[^>]*>CI\s', html)
ci_th2 = re.findall(r'<th[^>]*>CI 90%', html)
print(f"  <th>CI column headers: {len(ci_th)}")
print(f"  <th>CI 90% columns: {len(ci_th2)}")

# Count ci-tip tooltips
ci_tips = re.findall(r'class="ci-tip"', html)
print(f"  ci-tip tooltip elements: {len(ci_tips)}")

# Lint E2 check
from gem_report_lint import lint_doc
findings = lint_doc(doc)
e2 = [f for f in findings if f.rule == 'E2']
blockers = [f for f in findings if f.severity == 'BLOCKER']
errors = [f for f in findings if f.severity == 'ERROR']
print(f"  E2 findings: {len(e2)}")
print(f"  Total BLOCKER: {len(blockers)}")
print(f"  Total ERROR: {len(errors)}")
for b in blockers:
    print(f"    BLOCKER {b.rule}: {b.message}")

print()
print("=" * 60)
print("Q3: GTOW BUTTONS — LIVE OR GATED?")
print("=" * 60)

# Check for GTOW buttons in the rendered body
gtow_sims = html.count('GTOW sim')
gtow_approx = html.count('Open comparable GTOW spot')
gtow_unavail = html.count('GTOW unavailable')
gtow_urls = re.findall(r'data-gtow-url', html)
print(f"  'GTOW sim' buttons: {gtow_sims}")
print(f"  'Open comparable GTOW spot' buttons: {gtow_approx}")
print(f"  'GTOW unavailable' buttons: {gtow_unavail}")
print(f"  data-gtow-url attributes: {len(gtow_urls)}")
total_gtow = gtow_sims + gtow_approx + gtow_unavail
print(f"  TOTAL GTOW buttons rendered: {total_gtow}")
if total_gtow > 0:
    print("  STATUS: GTOW buttons are LIVE — no feature flag gates them")
else:
    print("  STATUS: no GTOW buttons in this render (hands may lack app_details)")

# Check if there's a feature-flag gate in sections_xiv.py
import gem_report_draft.sections_xiv as sxiv
src = open(sxiv.__file__, encoding='utf-8').read()
has_gtow_flag = 'gtow_links' in src or 'enable_gtow' in src or 'gtow_enabled' in src
print(f"  Feature flag in sections_xiv.py: {has_gtow_flag}")

print()
print("=" * 60)
print("Q5: UNIVERSAL-PILL GATE — ORPHAN COUNT")
print("=" * 60)

cited = set(_state._CITATIONS.keys())
appendix = set(_state._APPENDIX_HAND_IDS)
orphans = cited - appendix
print(f"  Cited hand IDs: {len(cited)}")
print(f"  Appendix hand IDs: {len(appendix)}")
print(f"  Orphan pills: {len(orphans)}")
if orphans:
    for o in sorted(orphans):
        print(f"    ORPHAN: {o}")
else:
    print("  CLEAN: zero orphan pills")

print()
print("=" * 60)
print("Q4: GTOW MANIFEST (building...)")
print("=" * 60)

import gem_gtow
manifest_rows = []
for hid, h in s.get('_hands_by_id', {}).items():
    det = rd.get('appendix_hand_details', {}).get(hid, {})
    manifest_rows.append((h, det))

manifest = gem_gtow.build_manifest(manifest_rows, rd)
print(f"  Manifest rows: {len(manifest)}")
for row in manifest:
    print(f"    {row['hand_id']}: status={row['link_status']}, "
          f"street={row['street']}, url={row['url'][:80] if row['url'] else 'None'}...")

# Write manifest to file
manifest_path = '_gtow_manifest.json'
with open(manifest_path, 'w', encoding='utf-8') as f:
    json.dump(manifest, f, indent=2)
print(f"  Manifest written to: {manifest_path}")

print()
print("DONE — review above output for each question.")
