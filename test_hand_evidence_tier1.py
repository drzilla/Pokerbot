#!/usr/bin/env python3
"""Supplemental tests for Tier 1 hand_evidence migration.

Validates:
  1. Citation-timing: _hand_ref() side-effects fire at same execution point
  2. Citation-explicit timing: _record_citation_explicit same point
  3. Appendix-link round-trip: #sec-app-hand-XXXX present in rendered HTML
  4. <details> boundary: block NEVER contains <details>/<summary> tags
  5. X6 raw_reference: check-raise evidence renders as raw_reference

Usage:  python test_hand_evidence_tier1.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or '.')

from gem_report_draft import _state
from gem_report_draft._html import Doc, _md_to_html
from gem_report_draft._helpers import _hand_ref
from gem_report_draft._blocks import (
    hand_evidence_table_block, raw_reference_block, _block_to_lines
)


def test_citation_timing():
    """_hand_ref() citation side-effects fire at the same point: old vs new."""
    _state._reset_citations()
    # _APPENDIX_HAND_IDS stores FULL hand IDs (same form as h['id'])
    _state._APPENDIX_HAND_IDS = {'00012345678', '00087654321'}

    h1 = {'id': '00012345678', 'tournament': 'GG$32', 'date': '2026-05-25',
           'position': 'CO', 'stack_bb': 38.5}
    h2 = {'id': '00087654321', 'tournament': 'GG$16', 'date': '2026-05-25',
           'position': 'BTN', 'stack_bb': 22.0}

    # --- Old path ---
    doc_old = Doc()
    doc_old.section('sec-2-1', 'S2.1 Punts', 'test')
    hdr = '| Hand Reference | Cards | Type | EV | Source |'
    sep = '|---|---|---|---|---|'
    doc_old.w(hdr)
    doc_old.w(sep)
    ref1_old = _hand_ref(h1)
    doc_old.w(f'| {ref1_old} | AhKs | Punt | -15.2 BB | analyst |')
    ref2_old = _hand_ref(h2)
    doc_old.w(f'| {ref2_old} | 5h5c | Leak | -8.0 BB | detector |')
    doc_old.w('')
    old_cit_1 = _state._get_citations_for('00012345678')
    old_cit_2 = _state._get_citations_for('00087654321')

    # --- New path ---
    _state._reset_citations()
    doc_new = Doc()
    doc_new.section('sec-2-1', 'S2.1 Punts', 'test')
    _rows = []
    ref1_new = _hand_ref(h1)  # citation fires HERE — same point
    _rows.append(f'| {ref1_new} | AhKs | Punt | -15.2 BB | analyst |')
    ref2_new = _hand_ref(h2)  # citation fires HERE — same point
    _rows.append(f'| {ref2_new} | 5h5c | Leak | -8.0 BB | detector |')
    blk = hand_evidence_table_block('iii1-test', hdr, sep, _rows)
    for ln in _block_to_lines(blk):
        doc_new.w(ln)
    doc_new.w('')
    new_cit_1 = _state._get_citations_for('00012345678')
    new_cit_2 = _state._get_citations_for('00087654321')

    assert old_cit_1 == new_cit_1, f'Citation mismatch h1: {old_cit_1} vs {new_cit_1}'
    assert old_cit_2 == new_cit_2, f'Citation mismatch h2: {old_cit_2} vs {new_cit_2}'
    assert doc_old.lines == doc_new.lines, (
        f'Line mismatch:\n  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}')
    assert len(old_cit_1) > 0, 'No citations registered for h1'
    assert len(old_cit_2) > 0, 'No citations registered for h2'


def test_citation_explicit_timing():
    """_record_citation_explicit fires at same point (M6/M7 pattern)."""
    _state._reset_citations()
    _state._APPENDIX_HAND_IDS = {'00AABBCCDD'}

    h = {'id': '00AABBCCDD', 'tournament': 'Test', 'date': '2026-05-27',
         'position': 'SB', 'stack_bb': 15.0}

    # Old path
    doc_old = Doc()
    doc_old.section('sec-4-3', 'S4.3 Picks', 'test')
    doc_old.w('| # | Hand Reference | Cards | Signal |')
    doc_old.w('|---|---|---|---|')
    ref_old = _hand_ref(h)
    doc_old.w(f'| 1 | {ref_old} | AhKs | signal |')
    _state._record_citation_explicit('00AABBCCDD', 'sec-4-3', "S4.3 Picks")
    doc_old.w('')
    old_cit = _state._get_citations_for('00AABBCCDD')

    # New path
    _state._reset_citations()
    doc_new = Doc()
    doc_new.section('sec-4-3', 'S4.3 Picks', 'test')
    _rows = []
    ref_new = _hand_ref(h)
    _rows.append(f'| 1 | {ref_new} | AhKs | signal |')
    _state._record_citation_explicit('00AABBCCDD', 'sec-4-3', "S4.3 Picks")
    blk = hand_evidence_table_block('iii9-test',
        '| # | Hand Reference | Cards | Signal |', '|---|---|---|---|', _rows)
    for ln in _block_to_lines(blk):
        doc_new.w(ln)
    doc_new.w('')
    new_cit = _state._get_citations_for('00AABBCCDD')

    assert old_cit == new_cit, f'Explicit citation mismatch: {old_cit} vs {new_cit}'
    assert doc_old.lines == doc_new.lines, 'Line mismatch'
    assert len(old_cit) > 0, 'No explicit citations registered'


def test_appendix_link_roundtrip():
    """_hand_ref produces clickable #sec-app-hand-XXXX link in HTML."""
    _state._reset_citations()
    # _APPENDIX_HAND_IDS stores FULL hand IDs (same form as h['id'])
    _state._APPENDIX_HAND_IDS = {'00012345678'}

    h = {'id': '00012345678', 'tournament': 'GG$32', 'date': '2026-05-25',
         'position': 'CO', 'stack_bb': 38.5}

    hdr = '| Hand Reference | Cards |'
    sep = '|---|---|'
    ref = _hand_ref(h)
    row = f'| {ref} | AhKs |'

    blk = hand_evidence_table_block('app-rt', hdr, sep, [row])
    lines = _block_to_lines(blk)
    md = '\n'.join(lines)
    html = _md_to_html(md)

    assert '#sec-app-hand-12345678' in html, (
        f'Appendix link missing in HTML. Got: {html[:500]}')
    assert '<table class="data-table">' in html, 'No data-table in HTML'
    assert '<div class="table-scroll">' in html, 'No table-scroll wrapper in HTML'
    assert '12345678' in html, 'Hand ID missing'


def test_details_boundary():
    """M3/M7: <details> tags must be prose OUTSIDE the block.
    Block contains only the table rows. If <details> leaks into
    block lines, that is a BLOCKER."""
    hdr = '| Hand Reference | Cards | Cleared As | Verdict |'
    sep = '|---|---|---|---|'
    rows = ['| ref1 | AhKs | 3BP Flat | \U0001f44d III.3 Cleared |',
            '| ref2 | 5h5c | Cooler | ❄️ III.3 Cooler |']

    blk = hand_evidence_table_block('m3-boundary', hdr, sep, rows)
    lines = _block_to_lines(blk)

    for i, ln in enumerate(lines):
        assert '<details' not in ln.lower(), (
            f'BLOCKER: <details> tag found INSIDE block at line {i}: {ln!r}')
        assert '</details' not in ln.lower(), (
            f'BLOCKER: </details> tag found INSIDE block at line {i}: {ln!r}')
        assert '<summary' not in ln.lower(), (
            f'BLOCKER: <summary> tag found INSIDE block at line {i}: {ln!r}')

    # Block = header + sep + rows, nothing else
    assert len(lines) == 2 + len(rows), (
        f'Expected {2 + len(rows)} lines, got {len(lines)}')
    assert lines[0] == hdr
    assert lines[1] == sep


def test_x6_raw_reference():
    """X6 check-raise evidence: 8 columns rendered via raw_reference_block."""
    hdr = '| Hand Reference | Street | Board | Hand | Draw | Line | Net | Verdict |'
    sep = '|---|---|---|---|---|---|---|---|'
    row = '| ref | Flop | AdKs3h | TPTK | — | `xc` | +5.0 BB | ⚪ |'
    blk = raw_reference_block('viii-cr-test', hdr, sep, [row])
    lines = _block_to_lines(blk)
    assert lines[0] == hdr, f'Header mismatch: {lines[0]}'
    assert lines[1] == sep, f'Sep mismatch: {lines[1]}'
    assert lines[2] == row, f'Row mismatch: {lines[2]}'
    assert blk['type'] == 'raw_reference', f'Wrong type: {blk["type"]}'


# ============================================================
# Runner
# ============================================================

if __name__ == '__main__':
    tests = [
        test_citation_timing,
        test_citation_explicit_timing,
        test_appendix_link_roundtrip,
        test_details_boundary,
        test_x6_raw_reference,
    ]

    passed, failed = 0, []
    print()
    print('=' * 60)
    print('TIER 1 HAND_EVIDENCE SUPPLEMENTAL TESTS')
    print('=' * 60)

    for t in tests:
        try:
            t()
            print(f'  ✅ {t.__name__}')
            passed += 1
        except AssertionError as e:
            print(f'  \U0001f534 FAIL: {t.__name__}: {e}')
            failed.append(t.__name__)
        except Exception as e:
            print(f'  \U0001f534 FAIL: {t.__name__}: {type(e).__name__}: {e}')
            failed.append(t.__name__)

    print()
    print('=' * 60)
    if not failed:
        print(f'✅ ALL SUPPLEMENTAL TESTS PASSED — {passed}/{len(tests)}')
        sys.exit(0)
    else:
        print(f'\U0001f534 FAILED — {passed} passed, {len(failed)} failed')
        for n in failed:
            print(f'  • {n}')
        sys.exit(1)
