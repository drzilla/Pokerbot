#!/usr/bin/env python3
"""Content-parity test — Phase 4 structural-identity gate.

Verifies that splitting section emitters into sub-emitters (commits 2-3) and
later reordering them (commit 5) preserves the rendered content.

Four fingerprints, all order-independent:
  1. Block-registry identity  — same block IDs and types
  2. Prose-line multiset      — same set of non-blank lines
  3. Citation-count parity    — same number of citations per hand
  4. Table-row multiset       — same table rows (by text)

Commit 2: Section III wrapper output == four direct sub-emitter calls.
Commit 3: Section II  wrapper output == two direct sub-emitter calls.
Commit 5: reordered section_emitters list == old order (multiset parity).

Usage:  python -X utf8 test_content_parity.py
"""

import sys, os, collections

_HERE = os.path.dirname(os.path.abspath(__file__)) or '.'
sys.path.insert(0, _HERE)

from gem_report_draft._html import Doc
from gem_report_draft import _state
from gem_report_draft._blocks import ALLOWED_BLOCK_TYPES
from gem_report_draft.sections_mistakes import (
    _emit_section_iii,
    _emit_iii_punts_mistakes,
    _emit_iii_strategic_leaks,
    _emit_iii_cleared_justified,
    _emit_iii_clinical_picks,
)
from gem_report_draft.sections_financial import (
    _emit_section_ii,
    _emit_ii_verdict_kpis,
    _emit_ii_mental_bluff,
)
from gem_report_draft.sections_xiv import _generate_cheat_sheet
from gem_report_draft.draft import _build


# ============================================================
# Minimal fixture — exercises Section III code paths
# ============================================================

def _minimal_fixture():
    """Build (stats, report_data, hands) that exercises Section II + III
    without crashing.  Not a realistic session — just enough data to produce
    non-empty output from every sub-emitter."""
    hands = [
        {'id': 'TM10000001', 'cards': ['Ah', 'Kd'], 'position': 'BTN',
         'stack_bb': 50.0, 'net_bb': 2.5, 'tournament': 'Test',
         'date': '2026-05-27', 'vpip': True, 'pfr': True,
         'went_to_sd': True, 'won': True,
         'board': ['Ks', '7c', '2d', 'Th', '3s'],
         'table_size': '6', 'pot_type': 'SRP'},
        {'id': 'TM10000002', 'cards': ['Jh', 'Ts'], 'position': 'CO',
         'stack_bb': 45.0, 'net_bb': -3.0, 'tournament': 'Test',
         'date': '2026-05-27', 'vpip': True, 'pfr': False,
         'went_to_sd': False, 'won': False,
         'board': ['9c', '8d', '2s'],
         'table_size': '6', 'pot_type': 'SRP'},
    ]
    stats = {
        'volume': {'hands': len(hands), 'tournaments': 1,
                   'bullets': 1, 'date': '2026-05-27'},
        'mistakes': [],
        'punts': {'hands': [], 'count': 0},
        'core': {'vpip': 50.0}, 'csv_row': {'VPIP': 50.0}, 'cbet': {},
        'positions': {},
        'facing_action': {},
        'intra_session_arc': {},
        'deviation_summary': {},
        'postflop_deviations_v732': [],
        'preflop_deviations': [],
        'coolers': {'hands': []},
        'bluff_profile': {},
        '_hands_by_id': {h['id']: h for h in hands},
        '_table_size_breakdown': {
            '6': {'hands': 2, 'vpip_pct': 50.0, 'pfr_pct': 25.0,
                  'net_bb': -0.5, 'bb_per_100': -25.0},
        },
    }
    report_data = {
        'reviewed_mistakes': {},
        'analyst_commentary': {},
        'discipline_tier': {},
        'leak_persistence': {},
        'clinical_candidates': [],
        'bestplay_screen': [],
        'read_dependent_quant': {},
        'read_dependent_screen': [],
        'deviation_evidence': {},
        'appendix_hand_ids_all': [h['id'] for h in hands],
        'skill_band': {'emoji': '⚪', 'label': 'test'},
    }
    return stats, report_data, hands


def _setup_state(s):
    """Initialise _state globals to match what _build() does."""
    _state._reset_citations()
    _state._set_appendix_hand_ids(set(s.get('_hands_by_id', {}).keys()))


# ============================================================
# Rendering helpers
# ============================================================

def _render_iii_wrapper(s, rd, hands):
    """Render Section III using the wrapper function."""
    _setup_state(s)
    doc = Doc()
    _emit_section_iii(doc, s, rd, hands)
    cites = dict(_state._CITATIONS)
    return doc, cites


def _render_iii_direct(s, rd, hands):
    """Render Section III by calling four sub-emitters directly."""
    _setup_state(s)
    doc = Doc()
    _emit_iii_punts_mistakes(doc, s, rd, hands)
    _emit_iii_strategic_leaks(doc, s, rd, hands)
    _emit_iii_cleared_justified(doc, s, rd, hands)
    _emit_iii_clinical_picks(doc, s, rd, hands)
    cites = dict(_state._CITATIONS)
    return doc, cites


# ============================================================
# Fingerprint extractors
# ============================================================

def _block_id_set(doc):
    """Set of block IDs from the block registry."""
    return {entry['block']['id'] for entry in doc._block_registry}


def _block_type_multiset(doc):
    """Multiset of block types from the registry."""
    return collections.Counter(
        entry['block']['type'] for entry in doc._block_registry)


def _prose_multiset(doc):
    """Multiset of non-blank, non-sentinel lines (order-independent)."""
    return collections.Counter(
        line for line in doc.lines
        if line.strip()
        and not line.startswith('<<')
    )


def _table_row_multiset(doc):
    """Multiset of table-row lines (lines starting with '|')."""
    return collections.Counter(
        line for line in doc.lines if line.startswith('|')
    )


def _citation_snapshot(cites_dict):
    """Dict of hand_id -> citation count."""
    return {hid: len(entries) for hid, entries in cites_dict.items()}


def _first_diff(a, b):
    """Return human-readable description of first difference in two line lists."""
    for i, (la, lb) in enumerate(zip(a, b)):
        if la != lb:
            return f"line {i}: {la!r} != {lb!r}"
    if len(a) != len(b):
        return f"length mismatch: {len(a)} vs {len(b)}"
    return None


# ============================================================
# Section III parity tests (commit 2)
# ============================================================

def test_iii_wrapper_equals_direct():
    """Wrapper output is byte-identical to calling four sub-emitters directly."""
    s, rd, hands = _minimal_fixture()
    doc_w, _ = _render_iii_wrapper(s, rd, hands)
    doc_d, _ = _render_iii_direct(s, rd, hands)
    assert doc_w.lines == doc_d.lines, (
        f"Wrapper vs direct sub-emitter output diverged.\n"
        f"  wrapper lines: {len(doc_w.lines)}\n"
        f"  direct lines:  {len(doc_d.lines)}\n"
        f"  first diff: {_first_diff(doc_w.lines, doc_d.lines)}")


def test_iii_block_registry_valid():
    """Every block in Section III has a valid type and unique ID."""
    s, rd, hands = _minimal_fixture()
    doc, _ = _render_iii_wrapper(s, rd, hands)
    ids = []
    for entry in doc._block_registry:
        blk = entry['block']
        assert blk['type'] in ALLOWED_BLOCK_TYPES, (
            f"Block {blk['id']} has unknown type '{blk['type']}'")
        ids.append(blk['id'])
    dupes = [x for x, c in collections.Counter(ids).items() if c > 1]
    assert not dupes, f"Duplicate block IDs in Section III: {dupes}"


def test_iii_block_ids_parity():
    """Wrapper and direct renders produce the same block ID set."""
    s, rd, hands = _minimal_fixture()
    doc_w, _ = _render_iii_wrapper(s, rd, hands)
    doc_d, _ = _render_iii_direct(s, rd, hands)
    assert _block_id_set(doc_w) == _block_id_set(doc_d), (
        f"Block ID mismatch.\n"
        f"  only in wrapper: {_block_id_set(doc_w) - _block_id_set(doc_d)}\n"
        f"  only in direct:  {_block_id_set(doc_d) - _block_id_set(doc_w)}")


def test_iii_prose_multiset_parity():
    """Wrapper and direct renders produce the same prose-line multiset."""
    s, rd, hands = _minimal_fixture()
    doc_w, _ = _render_iii_wrapper(s, rd, hands)
    doc_d, _ = _render_iii_direct(s, rd, hands)
    ms_w = _prose_multiset(doc_w)
    ms_d = _prose_multiset(doc_d)
    assert ms_w == ms_d, (
        f"Prose multiset mismatch.\n"
        f"  only in wrapper: {ms_w - ms_d}\n"
        f"  only in direct:  {ms_d - ms_w}")


def test_iii_table_multiset_parity():
    """Wrapper and direct renders produce the same table-row multiset."""
    s, rd, hands = _minimal_fixture()
    doc_w, _ = _render_iii_wrapper(s, rd, hands)
    doc_d, _ = _render_iii_direct(s, rd, hands)
    t_w = _table_row_multiset(doc_w)
    t_d = _table_row_multiset(doc_d)
    assert t_w == t_d, (
        f"Table-row multiset mismatch.\n"
        f"  only in wrapper: {t_w - t_d}\n"
        f"  only in direct:  {t_d - t_w}")


def test_iii_citation_count_parity():
    """Wrapper and direct renders produce the same citation counts."""
    s, rd, hands = _minimal_fixture()
    _, cites_w = _render_iii_wrapper(s, rd, hands)
    _, cites_d = _render_iii_direct(s, rd, hands)
    snap_w = _citation_snapshot(cites_w)
    snap_d = _citation_snapshot(cites_d)
    assert snap_w == snap_d, (
        f"Citation count mismatch.\n"
        f"  wrapper: {snap_w}\n"
        f"  direct:  {snap_d}")


def test_iii_prose_nonempty():
    """Section III renders non-trivial prose content with the minimal fixture."""
    s, rd, hands = _minimal_fixture()
    doc, _ = _render_iii_wrapper(s, rd, hands)
    ms = _prose_multiset(doc)
    assert len(ms) > 5, (
        f"Only {len(ms)} non-blank prose lines rendered — fixture too thin?")


def test_iii_deterministic():
    """Two renders of Section III produce byte-identical output."""
    s, rd, hands = _minimal_fixture()
    doc1, cites1 = _render_iii_wrapper(s, rd, hands)
    doc2, cites2 = _render_iii_wrapper(s, rd, hands)
    assert doc1.lines == doc2.lines, (
        f"Non-deterministic render.\n"
        f"  first diff: {_first_diff(doc1.lines, doc2.lines)}")
    assert _citation_snapshot(cites1) == _citation_snapshot(cites2), (
        "Citation counts differ between two identical renders")


# ============================================================
# Section II rendering helpers (commit 3)
# ============================================================

def _render_ii_wrapper(s, rd, hands):
    """Render Section II using the wrapper function."""
    _setup_state(s)
    doc = Doc()
    _emit_section_ii(doc, s, rd, hands)
    cites = dict(_state._CITATIONS)
    return doc, cites


def _render_ii_direct(s, rd, hands):
    """Render Section II by calling two sub-emitters directly."""
    _setup_state(s)
    doc = Doc()
    _emit_ii_verdict_kpis(doc, s, rd, hands)
    _emit_ii_mental_bluff(doc, s, rd, hands)
    cites = dict(_state._CITATIONS)
    return doc, cites


# ============================================================
# Section II parity tests (commit 3)
# ============================================================

def test_ii_wrapper_equals_direct():
    """Wrapper output is byte-identical to calling two sub-emitters directly."""
    s, rd, hands = _minimal_fixture()
    doc_w, _ = _render_ii_wrapper(s, rd, hands)
    doc_d, _ = _render_ii_direct(s, rd, hands)
    assert doc_w.lines == doc_d.lines, (
        f"Section II wrapper vs direct sub-emitter output diverged.\n"
        f"  wrapper lines: {len(doc_w.lines)}\n"
        f"  direct lines:  {len(doc_d.lines)}\n"
        f"  first diff: {_first_diff(doc_w.lines, doc_d.lines)}")


def test_ii_block_ids_parity():
    """Wrapper and direct renders produce the same block ID set."""
    s, rd, hands = _minimal_fixture()
    doc_w, _ = _render_ii_wrapper(s, rd, hands)
    doc_d, _ = _render_ii_direct(s, rd, hands)
    assert _block_id_set(doc_w) == _block_id_set(doc_d), (
        f"Section II block ID mismatch.\n"
        f"  only in wrapper: {_block_id_set(doc_w) - _block_id_set(doc_d)}\n"
        f"  only in direct:  {_block_id_set(doc_d) - _block_id_set(doc_w)}")


def test_ii_prose_multiset_parity():
    """Wrapper and direct renders produce the same prose-line multiset."""
    s, rd, hands = _minimal_fixture()
    doc_w, _ = _render_ii_wrapper(s, rd, hands)
    doc_d, _ = _render_ii_direct(s, rd, hands)
    ms_w = _prose_multiset(doc_w)
    ms_d = _prose_multiset(doc_d)
    assert ms_w == ms_d, (
        f"Section II prose multiset mismatch.\n"
        f"  only in wrapper: {ms_w - ms_d}\n"
        f"  only in direct:  {ms_d - ms_w}")


def test_ii_table_multiset_parity():
    """Wrapper and direct renders produce the same table-row multiset."""
    s, rd, hands = _minimal_fixture()
    doc_w, _ = _render_ii_wrapper(s, rd, hands)
    doc_d, _ = _render_ii_direct(s, rd, hands)
    t_w = _table_row_multiset(doc_w)
    t_d = _table_row_multiset(doc_d)
    assert t_w == t_d, (
        f"Section II table-row multiset mismatch.\n"
        f"  only in wrapper: {t_w - t_d}\n"
        f"  only in direct:  {t_d - t_w}")


def test_ii_prose_nonempty():
    """Section II renders non-trivial prose content."""
    s, rd, hands = _minimal_fixture()
    doc, _ = _render_ii_wrapper(s, rd, hands)
    ms = _prose_multiset(doc)
    assert len(ms) > 3, (
        f"Only {len(ms)} non-blank prose lines in Section II — fixture too thin?")


def test_ii_deterministic():
    """Two renders of Section II produce byte-identical output."""
    s, rd, hands = _minimal_fixture()
    doc1, _ = _render_ii_wrapper(s, rd, hands)
    doc2, _ = _render_ii_wrapper(s, rd, hands)
    assert doc1.lines == doc2.lines, (
        f"Section II non-deterministic render.\n"
        f"  first diff: {_first_diff(doc1.lines, doc2.lines)}")


# ============================================================
# Phase 4.5: Universal-pill guarantee (no orphan pills)
# ============================================================

def test_universal_pill_no_orphans():
    """After _build(), every cited hand has a corresponding appendix card.

    Phase 4.5 §3 guarantee: the citation registry is a subset of the
    appendix hand-id set.  If this fails, a pill in the report would be
    a dead link (no hand-detail-card to open).
    """
    s, rd, hands = _minimal_fixture()
    doc = _build(s, rd, hands)
    cited = set(_state._CITATIONS.keys())
    appendix = set(_state._APPENDIX_HAND_IDS)
    orphans = cited - appendix
    assert not orphans, (
        f"Orphan pills found: {sorted(orphans)} "
        f"(cited but no appendix card)")


def test_citation_inverse_roundtrip():
    """_get_hands_for_section is the inverse of _get_citations_for.

    Phase 4.5 §2.2: the relevant-hands list popup uses the inverse lookup.
    Verify that section→hands and hands→section are consistent.
    """
    _state._reset_citations()
    _state._set_appendix_hand_ids({'TM001', 'TM002', 'TM003'})
    _state._set_current_section('sec-1', 'S1')
    _state._record_citation('TM001')
    _state._record_citation('TM002')
    _state._set_current_section('sec-2', 'S2')
    _state._record_citation('TM002')
    _state._record_citation('TM003')
    # Forward: hand → sections
    assert len(_state._get_citations_for('TM001')) == 1  # sec-1 only
    assert len(_state._get_citations_for('TM002')) == 2  # sec-1 + sec-2
    assert len(_state._get_citations_for('TM003')) == 1  # sec-2 only
    # Inverse: section → hands
    s1_hands = _state._get_hands_for_section('sec-1')
    s2_hands = _state._get_hands_for_section('sec-2')
    assert s1_hands == ['TM001', 'TM002'], f"S1 hands: {s1_hands}"
    assert s2_hands == ['TM002', 'TM003'], f"S2 hands: {s2_hands}"
    # Non-existent section
    assert _state._get_hands_for_section('sec-99') == []
    _state._reset_citations()


# ============================================================
# Regression: every segment gets a top-level <h2> heading
# ============================================================

def test_all_18_segments_have_h2():
    """After _build(), rendered HTML has <h2 id="sec-N"> for every active segment.

    Regression test: Phase 4 sub-emitters carved from Section II/III
    originally used doc.subsection() (→ <h3>) for their entry heading
    instead of doc.section() (→ <h2>). This test catches that class of
    bug for any current or future segment.

    Phase 4.8: S16 (Glossary) RESTORED. 19 segments: sec-0 (TL;DR) + sec-1..18.
    Order: S0,S7,S1,S6,S2,S3,S4,S8,S9,S10,S11,S13,S5,S12,S14,S15,S16,S17,S18
    """
    import re
    s, rd, hands = _minimal_fixture()
    doc = _build(s, rd, hands)
    html = doc.render_html()

    # Match both regular <h2 id="sec-N"> and collapsed <h2 style=...> after
    # an anchor <a id="sec-N"> (used for QA/Raw Stats/Glossary/Deviation/Appendix)
    # v8.2.1: broadened to match sec-issue-explorer (non-numeric slug)
    h2_pattern = re.compile(r'<h2\s+id="(sec-[\w-]+)"')
    anchor_pattern = re.compile(r'(?:<a\s[^>]*id="(sec-[\w-]+)"[^>]*>|id="(sec-[\w-]+)")')
    found_ids = [m.group(1) for m in h2_pattern.finditer(html)]
    # Also find anchors for collapsed sections (h2 is inside <details>)
    for m in anchor_pattern.finditer(html):
        _aid = m.group(1) or m.group(2)
        if _aid and _aid.startswith('sec-') and _aid not in found_ids:
            # Verify there's an h2 nearby (within 200 chars)
            _pos = m.end()
            _nearby = html[_pos:_pos+200]
            if '<h2' in _nearby:
                found_ids.append(_aid)
    found_set = set(found_ids)
    # 18 segments + Issue Explorer: sec-0 (TL;DR) + sec-issue-explorer + sec-1..18, minus sec-7
    # (Coach removed — dashboard covers session reading, discipline, outcome drivers)
    expected = {'sec-0', 'sec-issue-explorer'} | {f'sec-{i}' for i in range(1, 19)} - {'sec-7'}

    missing = sorted(expected - found_set)
    assert not missing, (
        f"Segments missing <h2> heading (rendered as <h3> or absent): "
        f"{missing}")

    extra = sorted(found_set - expected)
    assert not extra, (
        f"Unexpected <h2 id=\"sec-N\"> headings: {extra}")

    # v8.2.1: Issue Explorer (sec-issue-explorer) moved to #2 after Summary.
    # sec-7 (Coach) removed — dashboard covers its content
    expected_order = ['sec-0', 'sec-issue-explorer', 'sec-1', 'sec-5', 'sec-6',
                      'sec-2', 'sec-3', 'sec-4', 'sec-8', 'sec-9', 'sec-10',
                      'sec-11', 'sec-13', 'sec-12', 'sec-14', 'sec-15', 'sec-16',
                      'sec-17', 'sec-18']
    assert found_ids == expected_order, (
        f"<h2> headings not in user's desired order.\n"
        f"  expected: {expected_order}\n"
        f"  got:      {found_ids}")


# ============================================================
# Phase 4.5: Enriched fixture for integration tests
# ============================================================

import re as _re

def _enriched_fixture():
    """Build (stats, report_data, hands) with body-section citations,
    populated appendix with app_details, and GTOW-testable hand structures.

    TM10000001: HU postflop (BTN raise, BB calls) → GTOW 'ready'
                analyst verdict III.1 Punt → cited in S2 body section
    TM10000002: 3-way to flop (CO open, BTN call, BB call) → GTOW 'unavailable'
                analyst verdict III.3 Cleared → cited in S13 body section
    TM10000003: preflop-only (HJ open, everyone folds) → GTOW 'partial'
                analyst verdict III.3 Cleared → cited in S13 body section
    """
    hands = [
        {'id': 'TM10000001', 'cards': ['Ah', 'Kd'], 'position': 'BTN',
         'stack_bb': 50.0, 'net_bb': -12.5, 'tournament': 'Test Tourney',
         'date': '2026-05-27', 'vpip': True, 'pfr': True,
         'went_to_sd': True, 'won': False,
         'board': ['Ks', '7c', '2d', 'Th', '3s'],
         'table_size': '6', 'pot_type': 'SRP',
         'format': 'MTT', 'level': '5',
         'eff_stack_bb': 45.0, 'spr': 4.5,
         'tournament_phase': 'post_reg', 'players_at_flop': 2,
         'pf_sequence': ['UTG:folds', 'MP:folds', 'CO:folds',
                         'BTN(H):raises', 'SB:folds', 'BB:calls']},
        {'id': 'TM10000002', 'cards': ['Jh', 'Ts'], 'position': 'CO',
         'stack_bb': 45.0, 'net_bb': 3.0, 'tournament': 'Test Tourney',
         'date': '2026-05-27', 'vpip': True, 'pfr': True,
         'went_to_sd': True, 'won': True,
         'board': ['9c', '8d', '2s'],
         'table_size': '6', 'pot_type': 'SRP',
         'format': 'MTT', 'level': '5',
         'eff_stack_bb': 40.0, 'spr': 3.8,
         'tournament_phase': 'post_reg', 'players_at_flop': 3,
         'pf_sequence': ['UTG:folds', 'CO(H):raises', 'BTN:calls',
                         'SB:folds', 'BB:calls']},
        {'id': 'TM10000003', 'cards': ['Qh', 'Qd'], 'position': 'HJ',
         'stack_bb': 55.0, 'net_bb': 1.5, 'tournament': 'Test Tourney',
         'date': '2026-05-27', 'vpip': True, 'pfr': True,
         'went_to_sd': False, 'won': True,
         'board': [],
         'table_size': '6', 'pot_type': 'UNO',
         'format': 'MTT', 'level': '5',
         'eff_stack_bb': 50.0,
         'tournament_phase': 'post_reg', 'players_at_flop': 0,
         'pf_sequence': ['UTG:folds', 'HJ(H):raises', 'CO:folds',
                         'BTN:folds', 'SB:folds', 'BB:folds']},
    ]

    # HU postflop app_details for TM10000001
    app1_seats = [
        {'seat': 1, 'name': 'Hero', 'stack_chips': 5000, 'stack_bb': 50,
         'position': 'BTN', 'is_hero': True,
         'covers_hero': False, 'hero_covers': False},
        {'seat': 2, 'name': 'P1', 'stack_chips': 4500, 'stack_bb': 45,
         'position': 'BB', 'is_hero': False,
         'covers_hero': False, 'hero_covers': True},
    ]
    app1_actions = {
        'preflop': [
            {'name': 'Hero', 'position': 'BTN', 'action': 'raises',
             'amount_bb': 2.5, 'all_in': False, 'is_hero': True, 'stack_bb': 50},
            {'name': 'P1', 'position': 'BB', 'action': 'calls',
             'amount_bb': 2.5, 'all_in': False, 'is_hero': False, 'stack_bb': 45},
        ],
        'flop': [
            {'name': 'P1', 'position': 'BB', 'action': 'checks',
             'amount_bb': 0, 'all_in': False, 'is_hero': False, 'stack_bb': 45},
            {'name': 'Hero', 'position': 'BTN', 'action': 'bets',
             'amount_bb': 3, 'all_in': False, 'is_hero': True, 'stack_bb': 50},
            {'name': 'P1', 'position': 'BB', 'action': 'calls',
             'amount_bb': 3, 'all_in': False, 'is_hero': False, 'stack_bb': 45},
        ],
        'turn': [], 'river': [],
    }

    # 3-way postflop app_details for TM10000002 (multiway → GTOW unavailable)
    app2_seats = [
        {'seat': 1, 'name': 'Hero', 'stack_chips': 4500, 'stack_bb': 45,
         'position': 'CO', 'is_hero': True,
         'covers_hero': False, 'hero_covers': False},
        {'seat': 2, 'name': 'P1', 'stack_chips': 5000, 'stack_bb': 50,
         'position': 'BTN', 'is_hero': False,
         'covers_hero': True, 'hero_covers': False},
        {'seat': 3, 'name': 'P2', 'stack_chips': 4000, 'stack_bb': 40,
         'position': 'BB', 'is_hero': False,
         'covers_hero': False, 'hero_covers': True},
    ]
    app2_actions = {
        'preflop': [
            {'name': 'Hero', 'position': 'CO', 'action': 'raises',
             'amount_bb': 2.5, 'all_in': False, 'is_hero': True, 'stack_bb': 45},
            {'name': 'P1', 'position': 'BTN', 'action': 'calls',
             'amount_bb': 2.5, 'all_in': False, 'is_hero': False, 'stack_bb': 50},
            {'name': 'P2', 'position': 'BB', 'action': 'calls',
             'amount_bb': 2.5, 'all_in': False, 'is_hero': False, 'stack_bb': 40},
        ],
        'flop': [
            {'name': 'P2', 'position': 'BB', 'action': 'checks',
             'amount_bb': 0, 'all_in': False, 'is_hero': False, 'stack_bb': 40},
            {'name': 'Hero', 'position': 'CO', 'action': 'bets',
             'amount_bb': 4, 'all_in': False, 'is_hero': True, 'stack_bb': 45},
            {'name': 'P1', 'position': 'BTN', 'action': 'calls',
             'amount_bb': 4, 'all_in': False, 'is_hero': False, 'stack_bb': 50},
            {'name': 'P2', 'position': 'BB', 'action': 'folds',
             'amount_bb': 0, 'all_in': False, 'is_hero': False, 'stack_bb': 40},
        ],
        'turn': [], 'river': [],
    }

    # Preflop-only app_details for TM10000003 (HJ open, folds around → GTOW partial)
    app3_seats = [
        {'seat': 1, 'name': 'Hero', 'stack_chips': 5500, 'stack_bb': 55,
         'position': 'HJ', 'is_hero': True,
         'covers_hero': False, 'hero_covers': False},
        {'seat': 2, 'name': 'P1', 'stack_chips': 5000, 'stack_bb': 50,
         'position': 'CO', 'is_hero': False,
         'covers_hero': False, 'hero_covers': True},
        {'seat': 3, 'name': 'P2', 'stack_chips': 4800, 'stack_bb': 48,
         'position': 'BTN', 'is_hero': False,
         'covers_hero': False, 'hero_covers': True},
        {'seat': 4, 'name': 'P3', 'stack_chips': 4200, 'stack_bb': 42,
         'position': 'SB', 'is_hero': False,
         'covers_hero': False, 'hero_covers': True},
        {'seat': 5, 'name': 'P4', 'stack_chips': 4600, 'stack_bb': 46,
         'position': 'BB', 'is_hero': False,
         'covers_hero': False, 'hero_covers': True},
    ]
    app3_actions = {
        'preflop': [
            {'name': 'Hero', 'position': 'HJ', 'action': 'raises',
             'amount_bb': 2.2, 'all_in': False, 'is_hero': True, 'stack_bb': 55},
            {'name': 'P1', 'position': 'CO', 'action': 'folds',
             'amount_bb': 0, 'all_in': False, 'is_hero': False, 'stack_bb': 50},
            {'name': 'P2', 'position': 'BTN', 'action': 'folds',
             'amount_bb': 0, 'all_in': False, 'is_hero': False, 'stack_bb': 48},
            {'name': 'P3', 'position': 'SB', 'action': 'folds',
             'amount_bb': 0, 'all_in': False, 'is_hero': False, 'stack_bb': 42},
            {'name': 'P4', 'position': 'BB', 'action': 'folds',
             'amount_bb': 0, 'all_in': False, 'is_hero': False, 'stack_bb': 46},
        ],
        'flop': [], 'turn': [], 'river': [],
    }

    stats = {
        'volume': {'hands': len(hands), 'tournaments': 1,
                   'bullets': 1, 'date': '2026-05-27'},
        'mistakes': [],
        'punts': {'hands': [], 'count': 0},
        'core': {'vpip': 50.0}, 'csv_row': {'VPIP': 50.0}, 'cbet': {},
        'positions': {},
        'facing_action': {},
        'intra_session_arc': {},
        'deviation_summary': {},
        'postflop_deviations_v732': [],
        'preflop_deviations': [],
        'coolers': {'hands': []},
        'bluff_profile': {},
        '_hands_by_id': {h['id']: h for h in hands},
        '_table_size_breakdown': {
            '6': {'hands': 3, 'vpip_pct': 100.0, 'pfr_pct': 100.0,
                  'net_bb': -8.0, 'bb_per_100': -266.7},
        },
    }

    report_data = {
        'reviewed_mistakes': {},
        'analyst_commentary': {
            'TM10000001': {
                'verdict': 'III.1 Punt',
                'argument': 'Bad raise sizing into a dry board.',
                'key_decision': 'sizing',
                'spot': 'BTN open → cbet',
            },
            'TM10000002': {
                'verdict': 'III.3 Cleared',
                'argument': 'Standard CO open, good cbet.',
                'key_decision': 'cbet',
                'spot': 'CO open 3-way',
            },
            'TM10000003': {
                'verdict': 'III.3 Cleared',
                'argument': 'Standard HJ open, folds around.',
                'key_decision': 'open sizing',
                'spot': 'HJ open preflop',
            },
        },
        'discipline_tier': {},
        'leak_persistence': {},
        'clinical_candidates': [],
        'bestplay_screen': [],
        'read_dependent_quant': {},
        'read_dependent_screen': [],
        'deviation_evidence': {},
        'appendix_hand_ids_all': [h['id'] for h in hands],
        'skill_band': {'emoji': '⚪', 'label': 'test'},
        'appendix_hand_details': {
            'TM10000001': {
                'bb_size_chips': 100, 'is_bounty': False,
                'seats': app1_seats, 'actions': app1_actions,
                'showdown': {},
            },
            'TM10000002': {
                'bb_size_chips': 100, 'is_bounty': False,
                'seats': app2_seats, 'actions': app2_actions,
                'showdown': {},
            },
            'TM10000003': {
                'bb_size_chips': 100, 'is_bounty': False,
                'seats': app3_seats, 'actions': app3_actions,
                'showdown': {},
            },
        },
    }

    return stats, report_data, hands


# ============================================================
# Phase 4.5 Task A: GTOW feature-flag tests
# ============================================================

def test_gtow_flag_off_no_buttons():
    """With gtow_links OFF, GTOW buttons still appear (v2.0: always ON).

    The flag is no longer gated — buttons emit whenever hand data
    supports a valid GTOW URL. This test verifies the gate removal.
    """
    from gem_report_draft.draft import render_html
    s, rd, hands = _enriched_fixture()
    html = render_html(s, rd, hands, gtow_links=False)
    btn_elements = _re.findall(
        r'<(?:a|span)\s+class=["\'][^"\']*gtow-btn', html)
    # v2.0: gate removed — buttons appear regardless of flag
    assert len(btn_elements) >= 3, (
        f"GTOW always-on but found only {len(btn_elements)} gtow-btn "
        f"element(s) — expected at least 3 (one per hand)")


def test_gtow_flag_on_has_buttons():
    """GTOW buttons appear when hand data supports them."""
    from gem_report_draft.draft import render_html
    s, rd, hands = _enriched_fixture()
    html = render_html(s, rd, hands, gtow_links=True)
    btn_elements = _re.findall(
        r'<(?:a|span)\s+class=["\'][^"\']*gtow-btn', html)
    assert len(btn_elements) >= 3, (
        f"found only {len(btn_elements)} gtow-btn "
        f"element(s) — expected at least 3 (one per hand)")


def test_gtow_env_var_fallback():
    """GEM_GTOW_LINKS env var — irrelevant in v2.0 (always ON), but no crash."""
    import os
    from gem_report_draft.draft import render_html
    s, rd, hands = _enriched_fixture()
    old = os.environ.get('GEM_GTOW_LINKS')
    try:
        os.environ['GEM_GTOW_LINKS'] = '1'
        html = render_html(s, rd, hands, gtow_links=None)
        btn_elements = _re.findall(
            r'<(?:a|span)\s+class=["\'][^"\']*gtow-btn', html)
        assert len(btn_elements) >= 3, (
            f"GEM_GTOW_LINKS=1 but found only {len(btn_elements)} "
            f"gtow-btn elements — expected ≥3")
    finally:
        if old is None:
            os.environ.pop('GEM_GTOW_LINKS', None)
        else:
            os.environ['GEM_GTOW_LINKS'] = old


# ============================================================
# Phase 4.5 Task B: Integration tests (enriched fixture)
# ============================================================

def test_enriched_pills_have_matching_cards():
    """Every data-hand-id pill in the body has a matching hand-detail-card,
    and the pill count is NON-ZERO (proving the fixture creates real citations).
    """
    s, rd, hands = _enriched_fixture()
    doc = _build(s, rd, hands)
    html = doc.render_html()

    # Collect all pills (data-hand-id on links)
    pill_ids = set(_re.findall(r'data-hand-id=["\']([^"\']+)["\']', html))
    # Collect all hand-detail-card ids
    card_pattern = _re.compile(
        r"<article\s+class=['\"]hand-detail-card['\"]\s+data-hand-id=['\"]([^'\"]+)['\"]")
    card_ids = set(card_pattern.findall(html))

    # NON-ZERO pills: the enriched fixture must produce actual body citations
    assert len(pill_ids) > 0, (
        "Enriched fixture produced ZERO data-hand-id pills — "
        "body sections did not cite any hands")

    # Every pill must have a matching card
    orphans = pill_ids - card_ids
    assert not orphans, (
        f"Orphan pills (no matching hand-detail-card): {sorted(orphans)}")


def test_enriched_context_hands_panel_exists():
    """Phase 4.8 C3: the context-hands sidebar panel exists and the hand-ref
    pills embedded in section content provide the same citation data that the
    old relevant-hands-trigger divs provided.

    The context-hands panel is populated by JS at runtime (scanning .hand-ref
    pills in the visible .chapter section), so we only verify:
      1. The #context-hands container exists in the sidebar.
      2. Hand-ref pills exist within chapter sections (the JS data source).
      3. Every pill target has a hand-detail-card (same invariant as before).
    """
    s, rd, hands = _enriched_fixture()
    doc = _build(s, rd, hands)
    html = doc.render_html()

    # 1. Context-hands panel exists in sidebar
    assert 'id="context-hands"' in html, (
        "Missing #context-hands panel — sidebar should contain context-hands div")

    # 2. Hand-ref pills exist within chapter sections (data for context panel)
    pill_pattern = _re.compile(
        r"<a[^>]+class=['\"][^'\"]*hand-ref[^'\"]*['\"][^>]*"
        r"data-hand-id=['\"]([^'\"]+)['\"]")
    pills = pill_pattern.findall(html)
    assert len(pills) > 0, (
        "No hand-ref pills found — context-hands panel has no data source")

    # 3. Every pill target has a corresponding hand-detail-card
    card_pattern = _re.compile(
        r"<article\s+class=['\"]hand-detail-card['\"]\s+"
        r"data-hand-id=['\"]([^'\"]+)['\"]")
    all_cards = set(card_pattern.findall(html))
    pill_targets = set(pills)
    missing = pill_targets - all_cards
    assert not missing, (
        f"Hand-ref pills reference {sorted(missing)} but no hand-detail-card "
        f"exists for them — context panel would link to missing hands")


def test_enriched_modal_clone_resolves():
    """Every pill's data-hand-id can be resolved to a hand-detail-card,
    simulating the modal clone path (querySelector by data-hand-id).
    """
    s, rd, hands = _enriched_fixture()
    doc = _build(s, rd, hands)
    html = doc.render_html()

    # All unique pill targets
    pill_ids = set(_re.findall(
        r"<a[^>]+class=['\"][^'\"]*hand-ref[^'\"]*['\"][^>]*"
        r"data-hand-id=['\"]([^'\"]+)['\"]", html))

    # Cards available for cloning
    card_pattern = _re.compile(
        r"<article\s+class=['\"]hand-detail-card['\"]\s+"
        r"data-hand-id=['\"]([^'\"]+)['\"]")
    card_ids = set(card_pattern.findall(html))

    assert len(pill_ids) > 0, (
        "No hand-ref pills found — enriched fixture did not create body links")

    unresolvable = pill_ids - card_ids
    assert not unresolvable, (
        f"Modal clone would fail for pills: {sorted(unresolvable)} — "
        f"no hand-detail-card with matching data-hand-id")


def test_enriched_gtow_ready_and_disabled():
    """v2.0: All three fixture hands produce valid GTOW buttons.

    TM10000001: HU postflop  → ready (flop root link)
    TM10000002: 3-way post   → ready (GTOW supports ≤3-way)
    TM10000003: preflop-only → ready (hero decision point, R-code known)
    """
    from gem_report_draft.draft import render_html
    s, rd, hands = _enriched_fixture()
    html = render_html(s, rd, hands, gtow_links=True)

    # Check all three hands have ready GTOW buttons with data-gtow-url
    for hid_full, desc in [
        ('TM10000001', 'HU postflop'),
        ('TM10000002', '3-way postflop'),
        ('TM10000003', 'preflop-only'),
    ]:
        hid_short = hid_full[-8:]
        ready_pat = _re.compile(
            r"<a\s+class=['\"]gtow-btn['\"][^>]*data-hand-id=['\"]" +
            _re.escape(hid_short) +
            r"['\"][^>]*data-gtow-url=['\"]([^'\"]+)['\"]")
        ready_match = ready_pat.search(html)
        assert ready_match, (
            f"Hand {hid_short} ({desc}) should have a GTOW button "
            f"with data-gtow-url, but none found")
        url = ready_match.group(1)
        assert 'gtowizard.com' in url, (
            f"GTOW URL for {hid_short} does not contain gtowizard.com: {url}")


# ============================================================
# Phase 4.6 A2: Review persistence — JS structural check
# ============================================================

def test_review_persistence_js_wiring():
    """Verify the generator's JS has the required persistence architecture.

    This checks that the rendered HTML contains the sessionStorage/localStorage
    dual-store pattern, the _lsOK probe, and the copy button wiring.

    BEHAVIORAL VERIFICATION: The real behavioral test is in
    test_review_persistence_jsdom.js (Node.js + jsdom), which loads the
    actual generator-rendered HTML, runs its real <script>, and exercises:
      A. Normal mode: click pill → type → close → reopen → assert restored
         + hand-switching independence
      B. Blocked-localStorage: _lsOK=false → sessionStorage fallback works
         + localStorage receives no data + Copy button collects correctly
      C. Modal audit-row strip: clone has zero details.audit-row

    Run it with:  node test_review_persistence_jsdom.js
    """
    from gem_report_draft.draft import render_html
    s, rd, hands = _enriched_fixture()
    html = render_html(s, rd, hands)

    # Extract the <script> block
    script_match = _re.search(
        r'<script>\s*\(function\(\)\{(.*?)\}\)\(\);\s*</script>',
        html, _re.DOTALL)
    assert script_match, "Could not find the modal IIFE <script> block"
    js_body = script_match.group(1)

    # sessionStorage as primary store
    assert 'sessionStorage.setItem' in js_body, (
        "JS missing sessionStorage.setItem")
    assert 'sessionStorage.getItem' in js_body, (
        "JS missing sessionStorage.getItem")

    # localStorage capability probe
    assert '_lsOK' in js_body, "JS missing _lsOK flag"
    assert '_gem_probe' in js_body, "JS missing localStorage probe"

    # Dual-store architecture
    assert '_writeStore' in js_body, "JS missing _writeStore function"
    assert '_readStore' in js_body, "JS missing _readStore function"

    # Copy button — v29 moved copy to auditExport in _AUDIT_HTML; modal no
    # longer has its own copy button. Verify the global export button exists.
    assert 'audit-export-btn' in html, "HTML missing audit export button"
    assert 'auditExport' in html, "JS missing auditExport function"

    # Clipboard fallback
    assert 'execCommand' in html, "JS missing execCommand clipboard fallback"


# ============================================================
# Phase 4.6 A1: Modal clone strips audit-row
# ============================================================

def test_modal_clone_strips_audit_row():
    """openHand() JS must strip in-card audit-rows so modal shows only its
    own review section.  Three checks:
      1. Rendered HTML has at least one details.audit-row inside a
         hand-detail-card (proving REVIEWROW markers expand in cards).
      2. The openHand() JS contains the querySelectorAll strip call.
      3. The modal scaffold (#hand-modal) itself has no audit-row elements
         (the modal review section uses a different structure).
    """
    from gem_report_draft.draft import render_html
    s, rd, hands = _enriched_fixture()
    html = render_html(s, rd, hands)

    # 1. Cards contain audit-rows (the source material openHand clones)
    #    Pattern: <article class="hand-detail-card" ...> ... <details class="audit-row" ...> ... </article>
    card_with_audit = _re.compile(
        r'<article\s+class=["\']hand-detail-card["\'][^>]*>.*?'
        r'<details\s+class=["\']audit-row["\']',
        _re.DOTALL)
    assert card_with_audit.search(html), (
        "No hand-detail-card contains a details.audit-row — "
        "REVIEWROW markers are not being expanded inside cards")

    # 2. buildModalHand JS strips audit-rows from cloned children
    # Phase 4.8: v29 buildModalHand uses '.audit-row' selector (covers both
    # details.audit-row and any other audit-row elements)
    strip_pattern = _re.compile(
        r"querySelectorAll\(['\"]\.?(?:details\.)?audit-row['\"]\)"
        r"\.forEach\(function\(\w+\)\{\w+\.remove\(\);\}\)")
    assert strip_pattern.search(html), (
        "buildModalHand() JS does not contain the audit-row strip logic — "
        "modal clone will show duplicate review sections")

    # 3. Modal scaffold has no audit-row elements
    #    Extract the modal div and verify it's clean
    modal_section = _re.search(
        r'<div[^>]*id=["\']hand-modal["\'][^>]*>.*?</div>\s*</div>\s*</div>',
        html, _re.DOTALL)
    if modal_section:
        modal_html = modal_section.group(0)
        audit_in_modal = _re.findall(
            r'<details\s+class=["\']audit-row["\']', modal_html)
        assert len(audit_in_modal) == 0, (
            f"Modal scaffold contains {len(audit_in_modal)} audit-row "
            f"element(s) — should have zero (modal has its own review)")


# ============================================================
# Phase 4.6 B2: Layout grid — content wrapper verification
# ============================================================

def test_layout_grid_wraps_content():
    """The .layout > .sidebar + .main grid must wrap all report body
    content. Verifies:
      1. <main class="main"> exists and wraps at least one <h2>.
      2. <aside class="sidebar"> exists (placeholder for nav rail).
      3. Both live inside a .layout div.
      4. Report content (section h2 headings) is INSIDE .main, not outside.
    """
    from gem_report_draft.draft import render_html
    s, rd, hands = _enriched_fixture()
    html = render_html(s, rd, hands)

    # 1. layout div exists
    assert '<div class="layout">' in html, "Missing .layout grid wrapper"

    # 2. sidebar exists
    assert 'class="sidebar"' in html, "Missing .sidebar element"

    # 3. main element exists (Phase 4.8 C1: renamed .content → .main)
    assert '<main class="main">' in html, "Missing <main class='main'>"

    # 4. Report h2 headings are inside .main, not before it
    # Extract content between <main class="main"> and </main>
    content_match = _re.search(
        r'<main class="main">(.*?)</main>',
        html, _re.DOTALL)
    assert content_match, "Could not extract .main inner HTML"
    content_html = content_match.group(1)

    # Must contain at least 10 section h2 headings (we have 18 segments)
    h2_in_content = _re.findall(r'<h2\s+id="sec-', content_html)
    assert len(h2_in_content) >= 10, (
        f"Only {len(h2_in_content)} <h2 id='sec-...'> inside .main — "
        f"expected 10+; report content may have leaked outside wrapper")

    # 5. Hand-detail-cards are inside .main (may use single or double quotes)
    cards_in_content = _re.findall(
        r'class=["\']hand-detail-card["\']', content_html)
    assert len(cards_in_content) >= 1, (
        "No hand-detail-cards inside .main — cards leaked outside wrapper")

    # 6. Design tokens present
    assert ':root{' in html or ':root {' in html, (
        "Missing :root CSS design tokens")
    assert '--brand:' in html, "Missing --brand token"
    assert '--ink:' in html, "Missing --ink token"


def test_topbar_and_nav_rail():
    """Phase 4.6 B3/B4: topbar has stat cards sourced from generator KPIs;
    nav rail has section links matching the 18-segment order."""
    from gem_report_draft.draft import render_html
    s, rd, hands = _enriched_fixture()
    html = render_html(s, rd, hands)

    # Topbar exists
    assert '<header class="topbar">' in html, "Missing sticky topbar"
    assert 'class="stat-strip"' in html, "Missing stat strip in topbar"
    assert 'class="stat-card' in html, "Missing stat cards in topbar"

    # KPI values are from the generator (not hardcoded v29 values)
    n_hands = s.get('volume', {}).get('hands', 0)
    assert f"{n_hands:,}" in html, (
        f"Topbar does not contain hands count {n_hands:,}")

    # Brand lockup
    assert 'class="pb-logo"' in html, "Missing PB logo in topbar"
    assert 'class="brand-copy"' in html, "Missing brand copy in topbar"

    # Nav rail has section links
    assert 'class="nav-row"' in html, "Missing nav-row links in sidebar"
    # Count nav rows — should have at least 10 sections
    nav_rows = _re.findall(r'class="nav-row"', html)
    assert len(nav_rows) >= 10, (
        f"Only {len(nav_rows)} nav-rows — expected 10+ (one per segment)")

    # IntersectionObserver JS present
    assert 'IntersectionObserver' in html, (
        "Missing IntersectionObserver for nav active-tracking")


# ============================================================
# Runner
# ============================================================

if __name__ == "__main__":
    tests = [
        # Section III (commit 2)
        test_iii_wrapper_equals_direct,
        test_iii_block_registry_valid,
        test_iii_block_ids_parity,
        test_iii_prose_multiset_parity,
        test_iii_table_multiset_parity,
        test_iii_citation_count_parity,
        test_iii_prose_nonempty,
        test_iii_deterministic,
        # Section II (commit 3)
        test_ii_wrapper_equals_direct,
        test_ii_block_ids_parity,
        test_ii_prose_multiset_parity,
        test_ii_table_multiset_parity,
        test_ii_prose_nonempty,
        test_ii_deterministic,
        # Phase 4.5 universal-pill guarantee
        test_universal_pill_no_orphans,
        test_citation_inverse_roundtrip,
        # Full-build heading regression (Phase 4)
        test_all_18_segments_have_h2,
        # Phase 4.5 Task A: GTOW feature flag
        test_gtow_flag_off_no_buttons,
        test_gtow_flag_on_has_buttons,
        test_gtow_env_var_fallback,
        # Phase 4.5 Task B: integration (enriched fixture)
        test_enriched_pills_have_matching_cards,
        test_enriched_context_hands_panel_exists,
        test_enriched_modal_clone_resolves,
        test_enriched_gtow_ready_and_disabled,
        # Phase 4.6 A2: review persistence JS wiring (behavioral proof in jsdom)
        test_review_persistence_js_wiring,
        # Phase 4.6 A1: modal double-review fix
        test_modal_clone_strips_audit_row,
        # Phase 4.6 B2-B4: layout grid + design tokens + topbar + nav
        test_layout_grid_wraps_content,
        test_topbar_and_nav_rail,
    ]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✓ {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {fn.__name__}: {e}")
    total = passed + failed
    print(f"\n{'='*60}")
    print(f"test_content_parity: {passed}/{total} passed" +
          (f", {failed} FAILED" if failed else " — all green"))
    sys.exit(1 if failed else 0)
