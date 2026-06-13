#!/usr/bin/env python3
"""GEM Phase 3 Lint Test Suite.

Tests:
  Per-rule tests    — B1, B2, E1, E2, E3, E4, E5, E6, W1
  E1 both-dir proof — preserved descriptive header PASSES,
                       scrambled order FAILS
  I2 / I3           — extra columns, row-number prepend
  Suppression tests — _find_suppression, _maybe_suppress, registry
  Registry tests    — Doc.write_block populates _block_registry
  Gate tests        — soft gate (no raise), strict gate
  Format tests      — console summary, QA block

Usage:  python -X utf8 test_lint.py
"""

import sys, os

_HERE = os.path.dirname(os.path.abspath(__file__)) or '.'
sys.path.insert(0, _HERE)

from gem_report_draft._html import Doc
from gem_report_draft._blocks import (
    ALLOWED_BLOCK_TYPES,
    heading_block, prose_block, method_note_block,
    hand_evidence_table_block, financial_table_block,
    variance_ledger_block, leak_bucket_overview_block,
    profile_matrix_block, raw_reference_block,
    action_review_block,
)
from gem_report_lint import (
    lint_doc, Finding, TABLE_GRAMMAR, _SUPPRESSION_REGISTRY,
    _parse_header_cols, _find_suppression, _maybe_suppress,
    counts, format_console_summary, format_qa_block,
    lint_and_gate,
)


# ============================================================
# Helper
# ============================================================

def _doc(*blocks):
    """Create a Doc and emit blocks through write_block."""
    doc = Doc()
    for blk in blocks:
        doc.write_block(blk)
    return doc


# ============================================================
# B1 — unknown block type
# ============================================================

def test_b1_fires_on_unknown():
    doc = Doc()
    doc._block_registry.append({
        'block': {'type': 'BOGUS', 'id': 'bogus-1'},
        'start_line': 0, 'end_line': 0,
    })
    f = lint_doc(doc)
    b1 = [x for x in f if x.rule == 'B1']
    assert len(b1) == 1 and b1[0].severity == 'BLOCKER'
    assert 'BOGUS' in b1[0].message

def test_b1_all_known_pass():
    doc = Doc()
    for bt in sorted(ALLOWED_BLOCK_TYPES):
        doc._block_registry.append({
            'block': {'type': bt, 'id': f't-{bt}'},
            'start_line': 0, 'end_line': 0,
        })
    b1 = [x for x in lint_doc(doc) if x.rule == 'B1']
    assert len(b1) == 0, f"Unexpected B1: {b1}"


# ============================================================
# B2 — pipe-table hidden in prose
# ============================================================

def test_b2_fires_on_pipe_table():
    blk = prose_block('p-pipe', [
        'Intro text',
        '| Col1 | Col2 | Col3 |',
        '|---|---|---|',
        '| a | b | c |',
    ])
    b2 = [x for x in lint_doc(_doc(blk)) if x.rule == 'B2']
    assert len(b2) == 1 and b2[0].severity == 'WARNING'

def test_b2_clean_prose_passes():
    blk = prose_block('p-clean', ['Just text', 'More text'])
    b2 = [x for x in lint_doc(_doc(blk)) if x.rule == 'B2']
    assert len(b2) == 0


# ============================================================
# E1 — column order  (BOTH-DIRECTIONS PROOF)
# ============================================================

def test_e1_descriptive_header_PASSES():
    r"""E1 PASSES: hand_evidence with descriptive header at correct positions.

    Grammar : Hand | Cards | Spot | Review/Verdict | Impact | Why
    Actual  : Hand Reference | Cards | Type | Verdict | Impact | Why

    Anchor pos 0  "Hand Reference"  matches /hand|reference/  -> ok
    Anchor pos 1  "Cards"           matches /card/            -> ok
    Relative order  0 < 1  ->  preserved.
    """
    blk = hand_evidence_table_block(
        'he-good',
        '| Hand Reference | Cards | Type | Verdict | Impact | Why |',
        '|---|---|---|---|---|---|',
        ['| TM001 | AhKh | Punt | \U0001f44e | -12.5 | Overplayed |'])
    e1 = [x for x in lint_doc(_doc(blk)) if x.rule == 'E1']
    assert len(e1) == 0, (
        f"E1 should PASS for descriptive headers at §3 positions, "
        f"but fired: {e1}")

def test_e1_scrambled_order_FAILS():
    r"""E1 FAILS: hand_evidence with Cards and Hand swapped.

    Actual  : Cards | Hand Reference | Type | ...
    Anchor pos 0 expects /hand|reference/ but gets "Cards"     -> fail
    """
    blk = hand_evidence_table_block(
        'he-scrambled',
        '| Cards | Hand Reference | Type | Verdict | Impact | Why |',
        '|---|---|---|---|---|---|',
        ['| AhKh | TM001 | Punt | \U0001f44e | -12.5 | Overplayed |'])
    e1 = [x for x in lint_doc(_doc(blk)) if x.rule == 'E1']
    assert len(e1) >= 1, (
        f"E1 should FAIL for scrambled column order, but got 0 findings")
    assert e1[0].severity == 'ERROR'

def test_e1_financial_exact_passes():
    # #29: Updated to match actual 12-col emitter output.
    blk = financial_table_block(
        'fin-ok', 'financial_summary',
        '| Date | Tourneys | Bullets | $Cost | $Cash | $Net | ROI | ITM/B | Top1/B | Top5/B | FT/B | Avg BI |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
        ['| 2026-05-27 | 1 | 1 | $50 | $80 | $30 | 60.0% | 100% | 100% | 100% | 100% | $50 |'])
    e1 = [x for x in lint_doc(_doc(blk)) if x.rule == 'E1']
    assert len(e1) == 0

def test_e1_financial_scrambled_fails():
    # #29: Updated to match actual column names but scrambled order.
    blk = financial_table_block(
        'fin-bad', 'financial_summary',
        '| Tourneys | Date | Bullets | $Cost | $Cash | $Net | ROI | ITM/B | Top1/B | Top5/B | FT/B | Avg BI |',
        '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
        ['| 1 | 2026-05-27 | 1 | $50 | $80 | $30 | 60.0% | 100% | 100% | 100% | 100% | $50 |'])
    e1 = [x for x in lint_doc(_doc(blk)) if x.rule == 'E1']
    assert len(e1) >= 1 and e1[0].severity == 'ERROR'

def test_e1_hand_evidence_interleaved_extras_pass():
    """Tier 2 table with domain columns interleaved still passes
    if anchor relative order is preserved (#22: VII.1 Hero Pos)."""
    blk = hand_evidence_table_block(
        'he-t2',
        '| Hand Reference | Hero Pos | Cards | Board | Stack |',
        '|---|---|---|---|---|',
        ['| TM001 | BTN | AhKh | Kd2d5s | 25bb |'])
    e1 = [x for x in lint_doc(_doc(blk)) if x.rule == 'E1']
    assert len(e1) == 0, f"Interleaved extras should PASS: {e1}"


# ============================================================
# E2 — missing columns
# ============================================================

def test_e2_missing_columns():
    # #29: Updated — grammar now expects 12 cols; 3-col header triggers E2.
    blk = financial_table_block(
        'fin-short', 'financial_summary',
        '| Date | Tourneys | Bullets |',
        '|---|---|---|',
        ['| 2026-05-27 | 1 | 1 |'])
    e2 = [x for x in lint_doc(_doc(blk)) if x.rule == 'E2']
    assert len(e2) >= 1 and e2[0].severity == 'ERROR'

def test_e2_skips_positional():
    """E2 does not fire on positional (hand_evidence) tables."""
    blk = hand_evidence_table_block(
        'he-short', '| Hand Reference | Cards |', '|---|---|',
        ['| TM001 | AhKh |'])
    e2 = [x for x in lint_doc(_doc(blk)) if x.rule == 'E2']
    assert len(e2) == 0, f"E2 should skip positional tables: {e2}"


# ============================================================
# E3 — <details> inside block boundary
# ============================================================

def test_e3_details_blocker():
    blk = prose_block('p-det', [
        '<details><summary>Hidden</summary>',
        'Content', '</details>'])
    e3 = [x for x in lint_doc(_doc(blk)) if x.rule == 'E3']
    assert len(e3) >= 1 and e3[0].severity == 'BLOCKER'

def test_e3_clean_passes():
    blk = hand_evidence_table_block(
        'he-clean',
        '| Hand Reference | Cards | Type | Verdict | Impact | Why |',
        '|---|---|---|---|---|---|',
        ['| TM001 | AhKh | Punt | ok | -1 | test |'])
    e3 = [x for x in lint_doc(_doc(blk)) if x.rule == 'E3']
    assert len(e3) == 0

def test_e3_details_in_rows_blocker():
    """<details> in table row fires BLOCKER."""
    blk = hand_evidence_table_block(
        'he-det-row',
        '| Hand Reference | Cards | Type |',
        '|---|---|---|',
        ['| TM001 | AhKh | <details>bad</details> |'])
    e3 = [x for x in lint_doc(_doc(blk)) if x.rule == 'E3']
    assert len(e3) >= 1 and e3[0].severity == 'BLOCKER'


# ============================================================
# E4 — empty rows
# ============================================================

def test_e4_empty_rows():
    blk = hand_evidence_table_block(
        'he-empty',
        '| Hand Reference | Cards | Type | Verdict | Impact | Why |',
        '|---|---|---|---|---|---|',
        [])
    e4 = [x for x in lint_doc(_doc(blk)) if x.rule == 'E4']
    assert len(e4) == 1 and e4[0].severity == 'ERROR'

def test_e4_nonempty_passes():
    blk = hand_evidence_table_block(
        'he-rows',
        '| Hand Reference | Cards | Type | Verdict | Impact | Why |',
        '|---|---|---|---|---|---|',
        ['| TM001 | AhKh | Punt | ok | -1 | test |'])
    e4 = [x for x in lint_doc(_doc(blk)) if x.rule == 'E4']
    assert len(e4) == 0


# ============================================================
# E5 — separator column count mismatch
# ============================================================

def test_e5_mismatch():
    blk = hand_evidence_table_block(
        'he-sep-bad',
        '| Hand Reference | Cards | Type | Verdict | Impact | Why |',
        '|---|---|---|',  # 3 vs 6
        ['| TM001 | AhKh | Punt | ok | -1 | test |'])
    e5 = [x for x in lint_doc(_doc(blk)) if x.rule == 'E5']
    assert len(e5) == 1 and e5[0].severity == 'ERROR'

def test_e5_match_passes():
    blk = hand_evidence_table_block(
        'he-sep-ok',
        '| Hand Reference | Cards | Type | Verdict | Impact | Why |',
        '|---|---|---|---|---|---|',
        ['| TM001 | AhKh | Punt | ok | -1 | test |'])
    e5 = [x for x in lint_doc(_doc(blk)) if x.rule == 'E5']
    assert len(e5) == 0


# ============================================================
# E6 — duplicate block IDs (registry-level)
# ============================================================

def test_e6_duplicate_ids():
    doc = Doc()
    doc._block_registry = [
        {'block': {'type': 'prose', 'id': 'dup-1'}, 'start_line': 0, 'end_line': 1},
        {'block': {'type': 'prose', 'id': 'dup-1'}, 'start_line': 2, 'end_line': 3},
    ]
    e6 = [x for x in lint_doc(doc) if x.rule == 'E6']
    assert len(e6) == 1 and e6[0].severity == 'ERROR'
    assert 'dup-1' in e6[0].message

def test_e6_unique_passes():
    doc = _doc(
        prose_block('a', ['x']),
        prose_block('b', ['y']),
    )
    e6 = [x for x in lint_doc(doc) if x.rule == 'E6']
    assert len(e6) == 0


# ============================================================
# W1 — wide table (>8 columns)
# ============================================================

def test_w1_wide():
    hdr = '| ' + ' | '.join(f'C{i}' for i in range(10)) + ' |'
    sep = '|' + '|'.join(['---'] * 10) + '|'
    blk = raw_reference_block('wide', hdr, sep,
        ['| ' + ' | '.join(['x'] * 10) + ' |'])
    w1 = [x for x in lint_doc(_doc(blk)) if x.rule == 'W1']
    assert len(w1) == 1 and w1[0].severity == 'WARNING'

def test_w1_narrow_passes():
    blk = hand_evidence_table_block(
        'narrow',
        '| Hand Reference | Cards | Type | Verdict | Impact | Why |',
        '|---|---|---|---|---|---|',
        ['| TM001 | AhKh | Punt | ok | -1 | test |'])
    w1 = [x for x in lint_doc(_doc(blk)) if x.rule == 'W1']
    assert len(w1) == 0


# ============================================================
# I2 — extra columns appended
# ============================================================

def test_i2_extra_columns():
    blk = financial_table_block(
        'tpnl', 'tournament_pnl',
        '| Tourney | BI | Stack | Place | $Prize | ROI | Time | bb/100 |',
        '|---|---|---|---|---|---|---|---|',
        ['| T1 | $5 | 2000 | 1st | $50 | 900% | 2h | 15 |'])
    f = lint_doc(_doc(blk))
    i2 = [x for x in f if x.rule == 'I2']
    e1 = [x for x in f if x.rule == 'E1']
    e2 = [x for x in f if x.rule == 'E2']
    assert len(i2) == 1 and i2[0].severity == 'INFO'
    assert 'bb/100' in i2[0].message
    assert len(e1) == 0, f"No E1 expected: {e1}"
    assert len(e2) == 0, f"No E2 expected: {e2}"


# ============================================================
# I3 — row-number column prepended
# ============================================================

def test_i3_row_number():
    blk = hand_evidence_table_block(
        'he-num',
        '| # | Hand Reference | Cards | Type | Verdict | Impact | Why |',
        '|---|---|---|---|---|---|---|',
        ['| 1 | TM001 | AhKh | Punt | ok | -1 | test |'])
    i3 = [x for x in lint_doc(_doc(blk)) if x.rule == 'I3']
    assert len(i3) == 1 and i3[0].severity == 'INFO'
    assert i3[0].decision_num == 16


# ============================================================
# Suppression tests
# ============================================================

def test_suppression_find():
    r = _find_suppression('E1', 'variance_ledger')
    assert r is not None and r[0] == 25

def test_suppression_find_miss():
    r = _find_suppression('E1', 'financial_summary')
    assert r is None

def test_maybe_suppress_downgrades():
    findings = []
    _maybe_suppress(findings, 'E1', 'ERROR', 'vl-1',
                    'Column mismatch', 'variance_ledger')
    assert len(findings) == 1
    assert findings[0].severity == 'INFO'
    assert findings[0].rule == 'I1'
    assert findings[0].decision_num == 25
    assert '#25' in findings[0].message

def test_maybe_suppress_no_match():
    findings = []
    _maybe_suppress(findings, 'E1', 'ERROR', 'fs-1',
                    'Column mismatch', 'financial_summary')
    assert len(findings) == 1
    assert findings[0].severity == 'ERROR'
    assert findings[0].rule == 'E1'
    assert findings[0].decision_num is None

def test_suppression_registry_metric_entries_resolved():
    """#14 suppression entries removed — metric_status grammar implemented."""
    mt = [(d, r) for d, g, r, _ in _SUPPRESSION_REGISTRY
          if g == 'metric_table']
    assert len(mt) == 0, (
        f"#14 metric_table suppression entries should be removed "
        f"(metric_status grammar implemented), found {len(mt)}")


# ============================================================
# Block-registry tests
# ============================================================

def test_registry_populated():
    doc = Doc()
    blk = prose_block('reg-1', ['Line one', 'Line two'])
    doc.write_block(blk)
    assert len(doc._block_registry) == 1
    e = doc._block_registry[0]
    assert e['block'] is blk
    assert e['end_line'] > e['start_line']

def test_registry_multi_order():
    doc = Doc()
    ids = [f'm-{i}' for i in range(5)]
    for bid in ids:
        doc.write_block(prose_block(bid, [f'Block {bid}']))
    assert [e['block']['id'] for e in doc._block_registry] == ids

def test_registry_heading_block():
    doc = Doc()
    doc.write_block(heading_block('h1', 1, 'sec-test', 'Test', 'summary'))
    assert len(doc._block_registry) == 1
    assert doc._block_registry[0]['block']['type'] == 'heading'


# ============================================================
# Gate-behavior tests
# ============================================================

def test_soft_gate_blockers_reported_no_raise():
    """Soft gate: BLOCKERs reported, no exception."""
    doc = Doc()
    doc._block_registry.append({
        'block': {'type': 'INVALID', 'id': 'bad'},
        'start_line': 0, 'end_line': 0})
    f = lint_doc(doc)
    b, _, _, _ = counts(f)
    assert b >= 1

def test_clean_doc_zero_blockers():
    blk = hand_evidence_table_block(
        'ok',
        '| Hand Reference | Cards | Type | Verdict | Impact | Why |',
        '|---|---|---|---|---|---|',
        ['| TM001 | AhKh | Punt | ok | -1 | test |'])
    b, _, _, _ = counts(lint_doc(_doc(blk)))
    assert b == 0

def test_strict_gate_raises_on_blocker():
    """--strict-lint: SystemExit when BLOCKER found."""
    doc = Doc()
    doc._block_registry.append({
        'block': {'type': 'INVALID', 'id': 'bad'},
        'start_line': 0, 'end_line': 0})
    raised = False
    try:
        lint_and_gate(doc, strict_lint=True, qa_block=False)
    except SystemExit:
        raised = True
    assert raised, "Expected SystemExit from strict gate"

def test_strict_gate_clean_no_raise():
    blk = hand_evidence_table_block(
        'ok2',
        '| Hand Reference | Cards | Type | Verdict | Impact | Why |',
        '|---|---|---|---|---|---|',
        ['| TM001 | AhKh | Punt | ok | -1 | test |'])
    # Should NOT raise
    lint_and_gate(_doc(blk), strict_lint=True, qa_block=False)


# ============================================================
# Console summary + QA block format
# ============================================================

def test_console_summary_format():
    f = [
        Finding('B1', 'BLOCKER', 'x', 'msg', None),
        Finding('E1', 'ERROR', 'x', 'msg', None),
        Finding('W1', 'WARNING', 'x', 'msg', None),
        Finding('I2', 'INFO', 'x', 'msg', None),
        Finding('I3', 'INFO', 'x', 'msg', None),
    ]
    s = format_console_summary(f)
    assert '1 BLOCKER' in s and '1 ERROR' in s
    assert '1 WARNING' in s and '2 INFO' in s

def test_qa_block_has_details():
    f = [Finding('E1', 'ERROR', 'blk', 'Column mismatch', None)]
    lines = format_qa_block(f)
    joined = '\n'.join(lines)
    assert '<details' in joined and '</details>' in joined
    assert 'Column mismatch' in joined


# ============================================================
# B4 — orphan pills (universal-pill guarantee)
# ============================================================

def test_b4_orphan_pill_fires():
    """B4 fires BLOCKER when a cited hand has no appendix card."""
    from gem_report_draft import _state
    _state._reset_citations()
    _state._set_appendix_hand_ids({'TM001'})
    _state._set_current_section('sec-1', 'S1')
    _state._record_citation('TM001')   # has appendix — OK
    _state._record_citation('TM999')   # NO appendix — orphan
    doc = Doc()
    f = lint_doc(doc)
    b4 = [x for x in f if x.rule == 'B4']
    assert len(b4) == 1 and b4[0].severity == 'BLOCKER', (
        f"Expected 1 BLOCKER for TM999, got {b4}")
    assert 'TM999' in b4[0].message
    _state._reset_citations()

def test_b4_no_orphan_passes():
    """B4 passes when all cited hands have appendix cards."""
    from gem_report_draft import _state
    _state._reset_citations()
    _state._set_appendix_hand_ids({'TM001', 'TM002'})
    _state._set_current_section('sec-1', 'S1')
    _state._record_citation('TM001')
    _state._record_citation('TM002')
    doc = Doc()
    b4 = [x for x in lint_doc(doc) if x.rule == 'B4']
    assert len(b4) == 0, f"Unexpected B4: {b4}"
    _state._reset_citations()

def test_b4_empty_citations_passes():
    """B4 passes trivially when no citations exist."""
    from gem_report_draft import _state
    _state._reset_citations()
    _state._set_appendix_hand_ids(set())
    doc = Doc()
    b4 = [x for x in lint_doc(doc) if x.rule == 'B4']
    assert len(b4) == 0, f"Unexpected B4 with empty state: {b4}"
    _state._reset_citations()


# ============================================================
# B3 — contrast (Phase 4.5 activation)
# ============================================================

def test_b3_fires_on_bad_contrast():
    """B3 detects a block with inline light-bg + white-text style."""
    doc = Doc()
    doc.write_block(prose_block('test-b3', [
        '<td style="background: #fef9c3; color: #fff;">bad contrast</td>',
    ]))
    b3 = [x for x in lint_doc(doc) if x.rule == 'B3']
    assert len(b3) >= 1, f"B3 should fire on light bg + white text, got {b3}"
    assert b3[0].severity == 'WARNING'


def test_b3_clean_passes():
    """B3 does not fire on blocks with good contrast."""
    doc = Doc()
    doc.write_block(prose_block('test-b3-ok', [
        '<td style="background: #2a8030; color: #ffffff;">good contrast</td>',
    ]))
    b3 = [x for x in lint_doc(doc) if x.rule == 'B3']
    assert len(b3) == 0, f"B3 should not fire on dark bg + white text, got {b3}"


# ============================================================
# _parse_header_cols unit test
# ============================================================

def test_parse_header_cols():
    assert _parse_header_cols('| A | B | C |') == ['A', 'B', 'C']
    assert _parse_header_cols('|---|---|---|') == ['---', '---', '---']
    assert _parse_header_cols('') == []


# ============================================================
# Runner
# ============================================================

def _run():
    tests = sorted(
        [(n, o) for n, o in globals().items()
         if n.startswith('test_') and callable(o)],
        key=lambda t: t[0])
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✓ {name}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {name}: {e}")
    print(f"\n{passed + failed} tests: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


# ============================================================
# v8.7.7: Board contradiction lint tests
# ============================================================

def test_board_flush_false_claim():
    """B-BOARD-FLUSH: argument claims flush-completing but board says no."""
    from gem_report_lint import _rule_board_contradictions, Finding
    findings = []
    stats = {'_hands_ref': [
        {'id': 'TM6042997501', 'board': ['5h', 'Qs', '8h', 'Qd', '4s'], 'cards': ['Kh', 'As']}
    ]}
    rd = {'analyst_commentary': {
        'TM6042997501': {'argument': 'The flush-completing river changes everything.', 'verdict': 'III.2'}
    }}
    _rule_board_contradictions(stats, rd, findings)
    assert len(findings) == 1, f'expected 1 finding, got {len(findings)}'
    assert findings[0].rule == 'B-BOARD-FLUSH'
    assert findings[0].severity == 'ERROR'

def test_board_flush_correct():
    """B-BOARD-FLUSH: correct flush description should NOT error."""
    from gem_report_lint import _rule_board_contradictions, Finding
    findings = []
    stats = {'_hands_ref': [
        {'id': 'TM_FLUSH', 'board': ['Ad', '8s', 'Ts', '2d', '9d'], 'cards': ['Kd', 'Qd']}
    ]}
    rd = {'analyst_commentary': {
        'TM_FLUSH': {'argument': 'The flush-completing river brings the third diamond.', 'verdict': 'III.2'}
    }}
    _rule_board_contradictions(stats, rd, findings)
    assert len(findings) == 0, f'expected 0 findings, got {len(findings)}: {[f.message for f in findings]}'

def test_board_straight_false_claim():
    """B-BOARD-STRAIGHT: argument claims straight completed but board says no."""
    from gem_report_lint import _rule_board_contradictions, Finding
    findings = []
    stats = {'_hands_ref': [
        {'id': 'TM_STR', 'board': ['5h', 'Qs', '8h', 'Qd', '4s'], 'cards': ['Kh', 'As']}
    ]}
    rd = {'analyst_commentary': {
        'TM_STR': {'argument': 'The straight-completing turn changes the action.', 'verdict': 'III.2'}
    }}
    _rule_board_contradictions(stats, rd, findings)
    assert len(findings) == 1
    assert findings[0].rule == 'B-BOARD-STRAIGHT'

def test_board_no_argument():
    """No argument = no lint."""
    from gem_report_lint import _rule_board_contradictions, Finding
    findings = []
    stats = {'_hands_ref': [
        {'id': 'TM_EMPTY', 'board': ['5h', 'Qs', '8h', 'Qd', '4s']}
    ]}
    rd = {'analyst_commentary': {
        'TM_EMPTY': {'argument': '', 'verdict': 'III.4'}
    }}
    _rule_board_contradictions(stats, rd, findings)
    assert len(findings) == 0


if __name__ == '__main__':
    sys.exit(_run())
