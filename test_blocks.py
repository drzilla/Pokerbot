#!/usr/bin/env python3
"""GEM Render-IR Block Test Suite — Phase 1 Equivalence Gate.

Three test levels:
  Level 1: Block-level line-identity (doc_old.lines == doc_new.lines)
           — 13 tests, one per §2 block type.
  Level 2: Doc integration smoke test (full render_html byte-identical).
  Level 3: Golden-fragment regression (structural + round-trip vs golden HTML).

Hard gate: in every Level 1 test, doc_old.lines == doc_new.lines must hold
EXACTLY.  A divergence means the block factory or helper call is wrong —
fix at source, never adjust the new path to mask a mismatch.

Usage:  python3 test_blocks.py
"""

import sys, os, re

_HERE = os.path.dirname(os.path.abspath(__file__)) or '.'
sys.path.insert(0, _HERE)

from gem_report_draft._html import Doc, _md_to_html, _html_escape
from gem_report_draft._blocks import (
    ALLOWED_BLOCK_TYPES,
    heading_block, prose_block, method_note_block, review_control_block,
    metric_table_block, financial_table_block, hand_evidence_table_block,
    variance_ledger_block, leak_bucket_overview_block, profile_matrix_block,
    action_review_block, coach_card_block, appendix_hand_block,
    _block_to_lines,
)
from gem_report_draft._helpers import _stat_row, _stat_row_pct


# ============================================================
# LEVEL 1 — Block-level line-identity tests (13 block types)
# ============================================================

def test_L1_heading_section():
    """heading block (level=1) produces identical lines to doc.section()."""
    doc_old = Doc()
    doc_old.section("sec-test-1", "I. Test Section", "test summary line")

    doc_new = Doc()
    doc_new.block(heading_block(
        "h-test-1", 1, "sec-test-1", "I. Test Section", "test summary line"
    ))

    assert doc_old.lines == doc_new.lines, (
        f"heading(level=1) line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")
    assert doc_old.toc == doc_new.toc, "TOC entries differ"


def test_L1_heading_subsection():
    """heading block (level=2) produces identical lines to doc.subsection()."""
    doc_old = Doc()
    doc_old.subsection("sec-sub-1", "I.1 Sub Section", "detail here")

    doc_new = Doc()
    doc_new.block(heading_block(
        "h-sub-1", 2, "sec-sub-1", "I.1 Sub Section", "detail here"
    ))

    assert doc_old.lines == doc_new.lines, (
        f"heading(level=2) line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")
    assert doc_old.toc == doc_new.toc, "TOC entries differ"
    assert doc_old._open_review == doc_new._open_review, "_open_review state differs"


def test_L1_prose():
    """prose block passes lines through verbatim."""
    lines = [
        "Some **bold** text with *italic* emphasis.",
        "",
        "- bullet one",
        "- bullet two",
        "",
    ]
    doc_old = Doc()
    for ln in lines:
        doc_old.w(ln)

    doc_new = Doc()
    doc_new.block(prose_block("p-test", lines))

    assert doc_old.lines == doc_new.lines, (
        f"prose line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")


def test_L1_method_note():
    """method_note block produces italic text + trailing blank line."""
    text = "*Methodology — why cEV is the spine (v7.63):*"

    doc_old = Doc()
    doc_old.w(text)
    doc_old.w("")

    doc_new = Doc()
    doc_new.block(method_note_block("mn-test", text))

    assert doc_old.lines == doc_new.lines, (
        f"method_note line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")


def test_L1_review_control():
    """review_control block produces the exact REVIEWROW sentinel."""
    doc_old = Doc()
    doc_old.w("<<REVIEWROW|sub|sec-iii-1|III.1 Range Oblivion / Punts>>")

    doc_new = Doc()
    doc_new.block(review_control_block(
        "rc-test", "sub", "sec-iii-1", "III.1 Range Oblivion / Punts"
    ))

    assert doc_old.lines == doc_new.lines, (
        f"review_control line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")


def test_L1_review_control_hand():
    """review_control block with rtype='hand' for appendix entries."""
    doc_old = Doc()
    doc_old.w("<<REVIEWROW|hand|TM12345678|Hand 12345678 — AhKh>>")

    doc_new = Doc()
    doc_new.block(review_control_block(
        "rc-hand", "hand", "TM12345678", "Hand 12345678 — AhKh"
    ))

    assert doc_old.lines == doc_new.lines, (
        f"review_control(hand) line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")


def test_L1_metric_table():
    """metric_table block produces identical STAT_HEADER + rows to
    stat_table_open() + _stat_row() calls."""
    doc_old = Doc()
    doc_old.stat_table_open()
    doc_old.w(_stat_row("VPIP", 278, 1510, 15, 21, notes="PF voluntary put"))
    doc_old.w(_stat_row("PFR", 211, 1510, 14, 20, notes="PF raise rate"))
    doc_old.w(_stat_row("3-Bet", 60, 480, 6, 9, notes="PF re-raise rate"))

    doc_new = Doc()
    doc_new.block(metric_table_block("mt-core", [
        {"name": "VPIP", "x": 278, "n": 1510, "target_lo": 15, "target_hi": 21,
         "notes": "PF voluntary put"},
        {"name": "PFR", "x": 211, "n": 1510, "target_lo": 14, "target_hi": 20,
         "notes": "PF raise rate"},
        {"name": "3-Bet", "x": 60, "n": 480, "target_lo": 6, "target_hi": 9,
         "notes": "PF re-raise rate"},
    ]))

    assert doc_old.lines == doc_new.lines, (
        f"metric_table line mismatch:\n"
        f"  OLD lines ({len(doc_old.lines)}):\n" +
        '\n'.join(f"    {i}: {l!r}" for i, l in enumerate(doc_old.lines)) +
        f"\n  NEW lines ({len(doc_new.lines)}):\n" +
        '\n'.join(f"    {i}: {l!r}" for i, l in enumerate(doc_new.lines)))


def test_L1_metric_table_pct_mode():
    """metric_table with pct_mode=True routes through _stat_row_pct."""
    doc_old = Doc()
    doc_old.stat_table_open()
    doc_old.w(_stat_row_pct("WTSD", 28.5, 650, 25, 32, notes="went to SD"))
    doc_old.w(_stat_row("ATS", 120, 340, 35, 45, notes="attempt to steal"))

    doc_new = Doc()
    doc_new.block(metric_table_block("mt-mixed", [
        {"name": "WTSD", "pct_mode": True, "pct": 28.5, "n": 650,
         "target_lo": 25, "target_hi": 32, "notes": "went to SD"},
        {"name": "ATS", "x": 120, "n": 340, "target_lo": 35, "target_hi": 45,
         "notes": "attempt to steal"},
    ]))

    assert doc_old.lines == doc_new.lines, (
        f"metric_table(pct_mode) line mismatch:\n"
        f"  OLD lines:\n" +
        '\n'.join(f"    {l!r}" for l in doc_old.lines) +
        f"\n  NEW lines:\n" +
        '\n'.join(f"    {l!r}" for l in doc_new.lines))


def test_L1_metric_table_with_link_and_aim():
    """metric_table with link_to and aim parameters."""
    doc_old = Doc()
    doc_old.stat_table_open()
    doc_old.w(_stat_row("Cold Call", 45, 300, 5, 15,
                        notes="non-blind", link_to="sec-v-3",
                        aim="aim ≥9.6"))

    doc_new = Doc()
    doc_new.block(metric_table_block("mt-link", [
        {"name": "Cold Call", "x": 45, "n": 300, "target_lo": 5, "target_hi": 15,
         "notes": "non-blind", "link_to": "sec-v-3", "aim": "aim ≥9.6"},
    ]))

    assert doc_old.lines == doc_new.lines, (
        f"metric_table(link+aim) line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")


def test_L1_metric_table_raw_string_rows():
    """metric_table with raw string rows — passthrough for manual rows."""
    raw_row = "| ↳ steal breakdown | — | BTN 55% · CO 40% · SB 35% | — | — | — | informational |"
    doc_old = Doc()
    doc_old.stat_table_open()
    doc_old.w(_stat_row("ATS", 120, 340, 35, 45, notes="steal"))
    doc_old.w(raw_row)

    doc_new = Doc()
    doc_new.block(metric_table_block("mt-raw", [
        {"name": "ATS", "x": 120, "n": 340, "target_lo": 35, "target_hi": 45,
         "notes": "steal"},
        raw_row,
    ]))

    assert doc_old.lines == doc_new.lines, (
        f"metric_table(raw) line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")

    # Block must have header/separator fields for lint
    blk = doc_new._block_registry[0]['block']
    assert 'header' in blk, "metric_table block missing 'header' field"
    assert 'separator' in blk, "metric_table block missing 'separator' field"
    assert blk['header'] == Doc.STAT_HEADER


def test_L1_financial_table():
    """financial_table block produces identical header + separator + rows."""
    header = "| Date | Tourneys | Bullets | $ Cost | $ Cash | $ Net | ROI | ITM/B | Top1/B | Top5/B | FT/B | Avg BI |"
    sep = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    row1 = "| 2026-05-25 | 15 | 18 | $720 | $1,250 | 🟢 **$+530** | +73.6% | 44.4% | 5.6% | 16.7% | 5.6% | $40 |"
    row2 = "| 2026-05-26 | 12 | 14 | $560 | $320 | 🔴 **$-240** | -42.9% | 28.6% | 0.0% | 7.1% | 0.0% | $40 |"

    doc_old = Doc()
    doc_old.w(header)
    doc_old.w(sep)
    doc_old.w(row1)
    doc_old.w(row2)

    doc_new = Doc()
    doc_new.block(financial_table_block(
        "ft-daily", "financial_summary", header, sep, [row1, row2]
    ))

    assert doc_old.lines == doc_new.lines, (
        f"financial_table line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")


def test_L1_hand_evidence_table():
    """hand_evidence_table block produces identical header + separator + rows."""
    header = "| Hand Reference | Cards | Type | EV | Source |"
    sep = "|---|---|---|---|---|"
    row1 = "| [`TM12345`](#sec-app-hand-12345) | AhKh | punt | -15.2bb | analyst |"
    row2 = "| [`TM67890`](#sec-app-hand-67890) | 5h5c | ISO punt | -30.0bb | analyst |"

    doc_old = Doc()
    doc_old.w(header)
    doc_old.w(sep)
    doc_old.w(row1)
    doc_old.w(row2)

    doc_new = Doc()
    doc_new.block(hand_evidence_table_block(
        "he-iii1", header, sep, [row1, row2]
    ))

    assert doc_old.lines == doc_new.lines, (
        f"hand_evidence_table line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")


def test_L1_variance_ledger():
    """variance_ledger block produces identical header + separator + rows."""
    header = "| Category | Count | Won | Actual | Expected | Status |"
    sep = "|---|---|---|---|---|---|"
    row1 = "| Preflop | 8 | 5 | +42.3bb | +38.1bb | 🟢 +4.2bb |"
    row2 = "| Postflop | 3 | 1 | -18.7bb | -5.2bb | 🔴 -13.5bb |"

    doc_old = Doc()
    doc_old.w(header)
    doc_old.w(sep)
    doc_old.w(row1)
    doc_old.w(row2)

    doc_new = Doc()
    doc_new.block(variance_ledger_block(
        "vl-eai", header, sep, [row1, row2]
    ))

    assert doc_old.lines == doc_new.lines, (
        f"variance_ledger line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")


def test_L1_leak_bucket_overview():
    """leak_bucket_overview block produces identical header + separator + rows."""
    header = "| # | Leak | Metric | Status | Analyst Judgment | Detail |"
    sep = "|---|---|---|---|---|---|"
    row1 = "| III.3.1 | Caller IP Agg (HU) | 45.0% (n=20) | 🔴 | confirmed real leak | probe frequency low |"

    doc_old = Doc()
    doc_old.w(header)
    doc_old.w(sep)
    doc_old.w(row1)

    doc_new = Doc()
    doc_new.block(leak_bucket_overview_block(
        "lb-iii3", header, sep, [row1]
    ))

    assert doc_old.lines == doc_new.lines, (
        f"leak_bucket_overview line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")


def test_L1_profile_matrix():
    """profile_matrix block produces identical header + separator + rows."""
    header = "| Position | Hands | VPIP | PFR | Open% | Target | Status | FI Opps | Opens | Limps | Missed | Flagged |"
    sep = "|---|---|---|---|---|---|---|---|---|---|---|---|"
    row1 = "| UTG | 220 | 12.3% | 10.0% | 10.0% | 10-16% | 🟢 On target | 220 | 22 | 0 | 198 | 0 |"
    row2 = "| CO | 215 | 28.4% | 24.7% | 26.5% | 24-32% | 🟢 On target | 215 | 57 | 4 | 154 | 2 |"

    doc_old = Doc()
    doc_old.w(header)
    doc_old.w(sep)
    doc_old.w(row1)
    doc_old.w(row2)

    doc_new = Doc()
    doc_new.block(profile_matrix_block(
        "pm-pos", header, sep, [row1, row2]
    ))

    assert doc_old.lines == doc_new.lines, (
        f"profile_matrix line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")


def test_L1_action_review():
    """action_review block produces identical header + separator + rows."""
    header = "| Street | 🙈 Missed | 🤷‍♂️ Ambiguous | 🛡️ Correctly Passive | 🎯 Correctly Aggressive | 🌋 Too Aggressive | Total |"
    sep = "|---|---|---|---|---|---|---|"
    row1 = "| Flop | 2 | 3 | 12 | 8 | 1 | 26 |"
    row2 = "| Turn | 1 | 1 | 8 | 5 | 0 | 15 |"

    doc_old = Doc()
    doc_old.w(header)
    doc_old.w(sep)
    doc_old.w(row1)
    doc_old.w(row2)

    doc_new = Doc()
    doc_new.block(action_review_block(
        "ar-bcd", header, sep, [row1, row2]
    ))

    assert doc_old.lines == doc_new.lines, (
        f"action_review line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")


def test_L1_coach_card():
    """coach_card block passes lines through verbatim."""
    lines = [
        "**🧭 The read:**",
        "",
        "Session variance was mildly lucky (+3.2 bb/100), driven by EAI wins.",
        "True EV sits at -1.8 bb/100 — a slight negative session.",
        "",
    ]

    doc_old = Doc()
    for ln in lines:
        doc_old.w(ln)

    doc_new = Doc()
    doc_new.block(coach_card_block("cc-read", lines))

    assert doc_old.lines == doc_new.lines, (
        f"coach_card line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")


def test_L1_appendix_hand():
    """appendix_hand block passes hand-grid + notes lines through verbatim."""
    lines = [
        '<table class="hand-grid">',
        '<thead><tr><th>Pre-Flop<br><span class="pot">Pot: 1.5bb</span></th></tr></thead>',
        '<tbody><tr><td class="street-actions">',
        '<span class="grid-action act-raise is-hero">Raise 3bb</span>',
        '</td></tr></tbody></table>',
        '<div class="analyst-notes">',
        '<p><span class="note-num">1</span> Standard open from CO.</p>',
        '</div>',
    ]

    doc_old = Doc()
    for ln in lines:
        doc_old.w(ln)

    doc_new = Doc()
    doc_new.block(appendix_hand_block("ah-TM123", lines))

    assert doc_old.lines == doc_new.lines, (
        f"appendix_hand line mismatch:\n"
        f"  OLD: {doc_old.lines}\n  NEW: {doc_new.lines}")


# ============================================================
# LEVEL 2 — Doc integration smoke test
# ============================================================

def test_L2_doc_integration_lines():
    """Multi-block Doc produces identical lines to equivalent doc.w() path.
    Tests: heading → metric_table → prose → subsection → hand_evidence."""

    # ---------- current path ----------
    doc_old = Doc()
    doc_old.section("sec-test", "Test Section", "integration test")
    doc_old.stat_table_open()
    doc_old.w(_stat_row("VPIP", 278, 1510, 15, 21, notes="test"))
    doc_old.w("Some prose between blocks.")
    doc_old.w("")
    doc_old.subsection("sec-sub", "Sub Section", "sub detail")
    doc_old.w("| Hand | Cards | Type |")
    doc_old.w("|---|---|---|")
    doc_old.w("| TM1234 | AhKh | punt |")

    # ---------- new path ----------
    doc_new = Doc()
    doc_new.block(heading_block("h1", 1, "sec-test", "Test Section",
                                "integration test"))
    doc_new.block(metric_table_block("mt1", [
        {"name": "VPIP", "x": 278, "n": 1510, "target_lo": 15,
         "target_hi": 21, "notes": "test"},
    ]))
    doc_new.block(prose_block("p1", ["Some prose between blocks.", ""]))
    doc_new.block(heading_block("h2", 2, "sec-sub", "Sub Section",
                                "sub detail"))
    doc_new.block(hand_evidence_table_block("he1",
        header="| Hand | Cards | Type |",
        separator="|---|---|---|",
        rows=["| TM1234 | AhKh | punt |"],
    ))

    # Hard gate: lines identical
    assert doc_old.lines == doc_new.lines, (
        f"L2 integration lines mismatch:\n"
        f"  OLD ({len(doc_old.lines)} lines):\n" +
        '\n'.join(f"    {i}: {l!r}" for i, l in enumerate(doc_old.lines)) +
        f"\n  NEW ({len(doc_new.lines)} lines):\n" +
        '\n'.join(f"    {i}: {l!r}" for i, l in enumerate(doc_new.lines)))

    # TOC must match
    assert doc_old.toc == doc_new.toc, (
        f"L2 TOC mismatch:\n  OLD: {doc_old.toc}\n  NEW: {doc_new.toc}")


def test_L2_render_html_identical():
    """Full render_html() output is byte-identical between old and new paths."""

    # ---------- current path ----------
    doc_old = Doc()
    doc_old.section("sec-demo", "Demo", "demo summary")
    doc_old.stat_table_open()
    doc_old.w(_stat_row("VPIP", 278, 1510, 15, 21, notes="test"))
    doc_old.w(_stat_row("PFR", 211, 1510, 14, 20, notes="raise"))
    doc_old.w("")
    doc_old.subsection("sec-demo-1", "Demo.1", "subsection")
    doc_old.w("**Bold** and *italic* text with `code`.")
    doc_old.w("")
    doc_old.w("| A | B |")
    doc_old.w("|---|---|")
    doc_old.w("| 1 | 2 |")

    # ---------- new path ----------
    doc_new = Doc()
    doc_new.block(heading_block("h1", 1, "sec-demo", "Demo", "demo summary"))
    doc_new.block(metric_table_block("mt1", [
        {"name": "VPIP", "x": 278, "n": 1510, "target_lo": 15,
         "target_hi": 21, "notes": "test"},
        {"name": "PFR", "x": 211, "n": 1510, "target_lo": 14,
         "target_hi": 20, "notes": "raise"},
    ]))
    doc_new.block(prose_block("p-blank", [""]))
    doc_new.block(heading_block("h2", 2, "sec-demo-1", "Demo.1",
                                "subsection"))
    doc_new.block(prose_block("p-text", [
        "**Bold** and *italic* text with `code`.", ""
    ]))
    doc_new.block(hand_evidence_table_block("t1",
        header="| A | B |", separator="|---|---|", rows=["| 1 | 2 |"]
    ))

    html_old = doc_old.render_html()
    html_new = doc_new.render_html()

    assert html_old == html_new, (
        f"L2 render_html mismatch — "
        f"old len={len(html_old)}, new len={len(html_new)}.\n"
        f"First difference at: {_first_diff(html_old, html_new)}")


def test_L2_render_md_identical():
    """Full render_md() output is byte-identical between old and new paths."""
    doc_old = Doc()
    doc_old.section("sec-md", "MD Test", "markdown equiv")
    doc_old.w("Some text.")
    doc_old.w("")
    doc_old.w("<<REVIEWROW|sub|sec-md|MD Test>>")

    doc_new = Doc()
    doc_new.block(heading_block("h1", 1, "sec-md", "MD Test", "markdown equiv"))
    doc_new.block(prose_block("p1", ["Some text.", ""]))
    doc_new.block(review_control_block("rc1", "sub", "sec-md", "MD Test"))

    md_old = doc_old.render_md()
    md_new = doc_new.render_md()

    assert md_old == md_new, (
        f"L2 render_md mismatch — "
        f"old len={len(md_old)}, new len={len(md_new)}.\n"
        f"First difference at: {_first_diff(md_old, md_new)}")


# ============================================================
# LEVEL 3 — Golden-fragment regression
# ============================================================

_GOLDEN_DIR = os.path.join(_HERE, 'golden')
_GOLDEN_5 = os.path.join(_GOLDEN_DIR, 'Pokerbot_Report_20260525_5.html')
_GOLDEN_7 = os.path.join(_GOLDEN_DIR, 'Pokerbot_Report_20260525_7.html')
_GOLDEN_27 = os.path.join(_GOLDEN_DIR, 'Pokerbot_Report_20260526-27.html')


def _read_golden(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return f.read()


def test_L3_golden_files_exist():
    """All three golden baselines are present and non-trivial."""
    for path, label in [(_GOLDEN_5, '20260525_5'),
                        (_GOLDEN_7, '20260525_7'),
                        (_GOLDEN_27, '20260526-27')]:
        assert os.path.exists(path), f"golden file missing: {label}"
        size = os.path.getsize(path)
        assert size > 500_000, (
            f"golden file {label} too small ({size} bytes) — "
            f"expected >500KB for a full report")


def test_L3_golden_has_metric_status_table():
    """Golden HTML contains at least one metric_status table with the
    canonical 6-column header."""
    html = _read_golden(_GOLDEN_5)
    if html is None:
        return  # no golden file — skip
    pat = (r'<th>Stat</th>\s*<th>Value \(n\)</th>\s*<th>CI 90%</th>\s*'
           r'<th>Target</th>\s*<th>Status</th>\s*<th>Notes</th>')
    m = re.search(pat, html)
    assert m, "golden file lacks a metric_status 6-column table header"


def test_L3_golden_has_hand_evidence_table():
    """Golden HTML contains at least one hand_evidence table."""
    html = _read_golden(_GOLDEN_5)
    if html is None:
        return
    # I.3 Large-Loss Audit or III.1 Punts
    assert ('<th>Hand Reference</th>' in html
            and '<th>Cards</th>' in html), (
        "golden file lacks a hand_evidence table header")


def test_L3_golden_has_toc_nav():
    """Golden HTML contains the TOC nav block."""
    html = _read_golden(_GOLDEN_5)
    if html is None:
        return
    assert '<nav class="toc" id="sec-toc">' in html, "golden file lacks TOC nav"
    assert '</nav>' in html, "golden file lacks closing </nav>"


def test_L3_golden_has_profile_matrix():
    """Golden HTML contains a position profile matrix table."""
    html = _read_golden(_GOLDEN_5)
    if html is None:
        return
    assert ('<th>Position</th>' in html
            and '<th>VPIP</th>' in html
            and '<th>PFR</th>' in html), (
        "golden file lacks profile_matrix table header")


def test_L3_golden_has_leak_bucket_overview():
    """Golden HTML contains a leak bucket overview table."""
    html = _read_golden(_GOLDEN_5)
    if html is None:
        return
    assert ('<th>Leak</th>' in html
            and '<th>Analyst Judgment</th>' in html), (
        "golden file lacks leak_bucket_overview table header")


def test_L3_golden_has_audit_review_rows():
    """Golden HTML contains B168 audit review controls."""
    html = _read_golden(_GOLDEN_5)
    if html is None:
        return
    assert 'class="audit-row"' in html, "golden file lacks audit review rows"
    assert 'class="audit-status"' in html, "golden file lacks audit status select"


def test_L3_metric_table_roundtrip():
    """Round-trip: construct a metric_table block, render to lines,
    convert through _md_to_html, verify the HTML contains a proper table
    with the correct cell values."""
    blk = metric_table_block("mt-rt", [
        {"name": "VPIP", "x": 278, "n": 1510, "target_lo": 15,
         "target_hi": 21, "notes": "PF voluntary put"},
        {"name": "PFR", "x": 211, "n": 1510, "target_lo": 14,
         "target_hi": 20, "notes": "PF raise rate"},
    ])
    lines = _block_to_lines(blk)
    md = "\n".join(lines)
    html = _md_to_html(md)

    # Must produce a valid HTML table
    # Phase 4.7 C1 / 4.8 C4: data-table + scroll wrapper + table-shell
    assert '<table class="data-table">' in html, "no data-table in rendered output"
    assert 'class="table-scroll"' in html, "missing table-scroll wrapper"
    assert 'class="table-shell"' in html, "missing table-shell outer wrapper"
    assert '</table></div></div>' in html, "no </table></div></div> closing"
    assert '<th>Metric</th>' in html, "missing Metric header"
    assert '<th>Notes</th>' in html, "missing Notes header"

    # Data rows must contain the metric names and values
    # Phase 4.6 B5: td cells now carry data-label for mobile card-mode
    assert 'VPIP</td>' in html, "VPIP cell missing"
    assert 'PFR</td>' in html, "PFR cell missing"
    assert 'n=1510' in html, "sample size missing"
    assert '15-21%' in html, "VPIP target range missing"
    assert 'PF voluntary put' in html, "VPIP notes missing"
    # Verify data-label is present on td cells
    assert 'data-label="Metric"' in html, "data-label missing on td cells"


def test_L3_financial_table_roundtrip():
    """Round-trip: financial_table block → lines → HTML → verify structure."""
    header = "| Date | Tourneys | $ Net |"
    sep = "|---|---|---|"
    row = "| 2026-05-25 | 15 | 🟢 **$+530** |"

    blk = financial_table_block("ft-rt", "financial_summary", header, sep, [row])
    lines = _block_to_lines(blk)
    md = "\n".join(lines)
    html = _md_to_html(md)

    # Phase 4.7 C1 / 4.8 C4: data-table + scroll wrapper + table-shell
    assert '<table class="data-table">' in html, "no data-table"
    assert 'class="table-scroll"' in html, "missing table-scroll wrapper"
    assert 'class="table-shell"' in html, "missing table-shell outer wrapper"
    assert '<th>Date</th>' in html, "Date header missing"
    assert '<th>Tourneys</th>' in html, "Tourneys header missing"
    assert '2026-05-25' in html, "date value missing"
    assert '$+530' in html, "net value missing"
    # Phase 4.6 B5: data-label present on td cells
    assert 'data-label="Date"' in html, "data-label missing on financial table"


def test_L3_golden_structure_consistency():
    """All three golden files share the same structural patterns:
    same CSS classes, same section structure, same renderer version.
    Golden files are from v7.99.19; re-baseline requires a full pipeline
    run with session data (Phase 4 commit 5 note)."""
    # TODO: regenerate goldens after first post-Phase-4 real session render;
    # current goldens are v7.99.19 with old Roman anchors, version check
    # relaxed to v7.99.*
    for path in [_GOLDEN_5, _GOLDEN_7, _GOLDEN_27]:
        html = _read_golden(path)
        if html is None:
            continue
        # CSS + document shell — accept current golden version or later
        assert 'v7.99.' in html, f"{path}: renderer version missing"
        assert 'class="toc"' in html, f"{path}: TOC class missing"
        assert 'class="audit-row"' in html or 'audit-export-btn' in html, \
            f"{path}: audit layer missing"
        # Key section anchors
        assert 'id="sec-toc"' in html, f"{path}: sec-toc missing"


# ============================================================
# Infrastructure tests
# ============================================================

def test_allowed_block_types_count():
    """14 block types: 13 from handoff §2 + raw_reference (§3, Phase 2)."""
    assert len(ALLOWED_BLOCK_TYPES) == 14, (
        f"Expected 14 block types, got {len(ALLOWED_BLOCK_TYPES)}: "
        f"{sorted(ALLOWED_BLOCK_TYPES)}")


def test_allowed_block_types_match_spec():
    """Block type names match §2 of GEM_Report_Redesign_Implementation_Handoff.md
    plus raw_reference added in Phase 2 for §3 XIII tables."""
    expected = {
        'coach_card', 'metric_table', 'hand_evidence_table',
        'financial_table', 'variance_ledger', 'leak_bucket_overview',
        'profile_matrix', 'action_review', 'raw_reference',
        'method_note', 'review_control', 'appendix_hand', 'prose', 'heading',
    }
    assert ALLOWED_BLOCK_TYPES == expected, (
        f"Block type mismatch vs spec:\n"
        f"  Missing: {expected - ALLOWED_BLOCK_TYPES}\n"
        f"  Extra: {ALLOWED_BLOCK_TYPES - expected}")


def test_unknown_block_type_raises():
    """_block_to_lines rejects unknown block types."""
    try:
        _block_to_lines({"type": "not_a_real_type", "id": "x"})
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "Unknown block type" in str(e)


def test_heading_block_to_lines_raises():
    """_block_to_lines rejects heading blocks (need Doc state)."""
    try:
        _block_to_lines(heading_block("x", 1, "a", "b", "c"))
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "Doc state" in str(e)


def test_every_non_heading_type_has_renderer():
    """Every non-heading block type has a registered renderer."""
    from gem_report_draft._blocks import _RENDERERS
    for btype in ALLOWED_BLOCK_TYPES:
        if btype == 'heading':
            continue
        assert btype in _RENDERERS, f"No renderer for block type: {btype}"


# ============================================================
# Helpers
# ============================================================

def _first_diff(a, b):
    """Return position and context of first character difference."""
    for i, (ca, cb) in enumerate(zip(a, b)):
        if ca != cb:
            ctx_a = a[max(0, i-20):i+20]
            ctx_b = b[max(0, i-20):i+20]
            return f"char {i}: old={ctx_a!r} vs new={ctx_b!r}"
    if len(a) != len(b):
        return f"lengths differ: old={len(a)} vs new={len(b)}"
    return "(identical)"


# ============================================================
# Runner
# ============================================================

if __name__ == "__main__":
    tests = [
        # Level 1 — block-level line-identity (13 block types)
        test_L1_heading_section,
        test_L1_heading_subsection,
        test_L1_prose,
        test_L1_method_note,
        test_L1_review_control,
        test_L1_review_control_hand,
        test_L1_metric_table,
        test_L1_metric_table_pct_mode,
        test_L1_metric_table_with_link_and_aim,
        test_L1_metric_table_raw_string_rows,
        test_L1_financial_table,
        test_L1_hand_evidence_table,
        test_L1_variance_ledger,
        test_L1_leak_bucket_overview,
        test_L1_profile_matrix,
        test_L1_action_review,
        test_L1_coach_card,
        test_L1_appendix_hand,
        # Level 2 — Doc integration
        test_L2_doc_integration_lines,
        test_L2_render_html_identical,
        test_L2_render_md_identical,
        # Level 3 — golden fragment regression
        test_L3_golden_files_exist,
        test_L3_golden_has_metric_status_table,
        test_L3_golden_has_hand_evidence_table,
        test_L3_golden_has_toc_nav,
        test_L3_golden_has_profile_matrix,
        test_L3_golden_has_leak_bucket_overview,
        test_L3_golden_has_audit_review_rows,
        test_L3_metric_table_roundtrip,
        test_L3_financial_table_roundtrip,
        test_L3_golden_structure_consistency,
        # Infrastructure
        test_allowed_block_types_count,
        test_allowed_block_types_match_spec,
        test_unknown_block_type_raises,
        test_heading_block_to_lines_raises,
        test_every_non_heading_type_has_renderer,
    ]

    passed, failed = 0, []
    print()
    print("=" * 60)
    print("GEM RENDER-IR BLOCK TEST SUITE — Phase 1")
    print("=" * 60)

    current_level = None
    for t in tests:
        # Print level headers
        name = t.__name__
        if name.startswith('test_L1_') and current_level != 'L1':
            current_level = 'L1'
            print("\n--- Level 1: Block-level line-identity ---")
        elif name.startswith('test_L2_') and current_level != 'L2':
            current_level = 'L2'
            print("\n--- Level 2: Doc integration ---")
        elif name.startswith('test_L3_') and current_level != 'L3':
            current_level = 'L3'
            print("\n--- Level 3: Golden-fragment regression ---")
        elif not name.startswith('test_L') and current_level != 'infra':
            current_level = 'infra'
            print("\n--- Infrastructure ---")

        try:
            t()
            print(f"  ✅ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  🔴 FAIL: {name}: {e}")
            failed.append(name)
        except Exception as e:
            print(f"  🔴 FAIL: {name}: {type(e).__name__}: {e}")
            failed.append(name)

    print()
    print("=" * 60)
    if not failed:
        print(f"✅ ALL TESTS PASSED — {passed}/{len(tests)}")
        sys.exit(0)
    else:
        print(f"🔴 FAILED — {passed} passed, {len(failed)} failed")
        print("\nFAILURES:")
        for n in failed:
            print(f"  • {n}")
        sys.exit(1)
