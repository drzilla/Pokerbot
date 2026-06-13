"""Phase 3 structural linter for the GEM render-IR block registry.

Inspects the block registry produced by Doc.write_block() and reports
findings at four severity levels:

    BLOCKER  — structural invariant violation; report may be corrupt
    ERROR    — grammar / schema mismatch; table is mis-shaped
    WARNING  — suspicious pattern; likely un-migrated or too wide
    INFO     — documented deviation, extra columns, or row-number prefix

Suppression: findings matching entries in PHASE2_GRAMMAR_DECISIONS.md
are downgraded to INFO and relabeled I1 (never silenced). Each suppressed
finding is tagged with the decision number for traceability.

Phase 4.5 addition: B4 (orphan-pill universal-pill guarantee) checks
the citation registry against the appendix hand-id set.

Phase 4.5 addition: B3 (contrast) activated — pattern-matches known
low-contrast combinations (light bg + light/white text). WARNING severity.

Phase 3b stubs: HTML-level rules (E3-full/E6-full, W2, B2-full)
are declared but not yet implemented — their absence is visible and
scheduled in the code.

Usage from draft.py:
    from gem_report_lint import lint_and_gate
    lint_and_gate(doc, strict_lint=False, qa_block=False)
"""

import re
from collections import namedtuple

from gem_report_draft._blocks import ALLOWED_BLOCK_TYPES


# ============================================================
# Finding record
# ============================================================

Finding = namedtuple('Finding', [
    'rule',          # str: rule id (B1, E1, I1, I2, ...)
    'severity',      # str: BLOCKER | ERROR | WARNING | INFO
    'block_id',      # str: the block's 'id' field
    'message',       # str: human-readable description
    'decision_num',  # int | None: PHASE2_GRAMMAR_DECISIONS.md entry
])


# ============================================================
# TABLE_GRAMMAR — §3 canonical column specifications
# ============================================================
# Grammar key resolution:
#   financial_table blocks → blk['table_type'] ('financial_summary' | 'tournament_pnl')
#   all other table blocks  → blk['type']
#
# Fields:
#   columns      : list[str]         — canonical §3 column names in order
#   strict_order : bool              — True = E1 enforces column order
#   positional   : bool              — True = anchor-based relative-order check
#                                      (§15 descriptive headers, not exact names)
#   anchors      : dict[int, str]    — position → regex for positional check

TABLE_GRAMMAR = {
    'financial_summary': {
        # #29: Updated to match actual 12-col emitter output (Phase 3/4 evolution).
        'columns': ['Date', 'Tourneys', 'Bullets', '$Cost', '$Cash', '$Net',
                     'ROI', 'ITM/B', 'Top1/B', 'Top5/B', 'FT/B', 'Avg BI'],
        'strict_order': True,
    },
    'tournament_pnl': {
        'columns': ['Tourney', 'BI', 'Stack', 'Place', '$Prize', 'ROI', 'Time'],
        'strict_order': True,
    },
    'variance_ledger': {
        'columns': ['Street', 'Matchup', 'Hero', 'Villain', 'Board',
                     'Pot BB', 'Equity', 'EV Diff'],
        'strict_order': True,
    },
    'leak_bucket_overview': {
        # #29: Updated to match actual emitter output (Phase 3/4 evolution).
        # Two variants: 6-col (S3 iii7-buckets) and 7-col (S8 iv2-buckets, +Detail).
        # Grammar covers the common 6 columns; the optional Detail column is
        # allowed as an appended extra (I2 informational, not E1 error).
        'columns': ['Status', 'Bucket', 'Rate', 'Acceptable',
                     'Common Hands', 'Count/Denom'],
        'strict_order': True,
    },
    'profile_matrix': {
        'columns': ['Position', 'Status', 'Rate', 'Target', 'Count', 'Opps', 'Notes'],
        'strict_order': True,
    },
    'hand_evidence_table': {
        'columns': ['Hand', 'Cards', 'Spot', 'Review/Verdict', 'Impact', 'Why'],
        'strict_order': True,
        'positional': True,
        # #15: descriptive headers at §3 positions — check by anchor pattern,
        # not by exact name.  Relative order of anchors must be preserved.
        'anchors': {
            0: r'(?i)\bhand\b|\breference\b',
            1: r'(?i)\bcard',
        },
    },
    'action_review': {
        'columns': ['Spot/Decision', 'Status', 'Count', 'EV Impact',
                     'Example Hands', 'Recommended'],
        'strict_order': True,
    },
    'raw_reference': {
        # §3: source order allowed — no grammar enforcement
        'columns': [],
        'strict_order': False,
    },
    'metric_status': {
        'columns': ['Metric', 'Status', 'Value/Rate', 'Target', 'Delta',
                     'Sample', 'Notes'],
        'strict_order': True,
    },
}


# ============================================================
# SUPPRESSION_REGISTRY — from PHASE2_GRAMMAR_DECISIONS.md
# ============================================================
# (decision_number, grammar_key, rule_id, reason)
# Matching findings are relabeled I1/INFO, tagged with #N.
#
# Most §3 deviations are handled by grammar design (I2 for extras,
# I3 for # prefix, positional mode for descriptive headers).  Only
# deviations that would otherwise be ERROR need explicit suppression.

_SUPPRESSION_REGISTRY = [
    # #14: RESOLVED — metric_status grammar implemented (Commit B).
    # All 6 stat tables block-registered, passing E1/E2/E5 cleanly.
    # 3 suppression entries removed.
    # #25: EAI summary tables use variance_ledger block type but render
    # aggregate category columns (Street/Category/Count/Won/Actual/
    # Expected/Delta/Status) instead of per-hand matchup columns
    # (Street/Matchup/Hero/Villain/Board/Pot BB/Equity/EV Diff).
    # Same block type, different analytical view.  Deferred until a
    # dedicated variance_summary grammar or subtype is added.
    (25, 'variance_ledger', 'E1',
     'EAI summary columns differ from per-hand §3 variance_ledger grammar'),
    # #26: Per-tourney P&L renders hand-history-derived performance
    # columns (Date/Tournament/Bullets/Hands/BI/NetBB/bb/100) instead
    # of §3 tournament_pnl columns (Tourney/BI/Stack/Place/$Prize/ROI/
    # Time).  §3 grammar describes tournament-results; renderer uses a
    # HH-derived breakdown.  Extends decisions #1-2 which documented
    # partial deviations.  Deferred until grammar redesign.
    (26, 'tournament_pnl', 'E1',
     'per-tourney PnL columns differ from §3 tournament_pnl grammar'),
    # #27: profile_matrix E4 (empty rows) fires only when position data
    # is absent — cannot happen in production (analyzer always computes
    # positions from hand history). The emitter unconditionally creates
    # the block; guard-before-create would be a functional change out of
    # Phase 4 scope.  Suppressed until the emitter adds an empty-guard.
    (27, 'profile_matrix', 'E4',
     'empty rows — position data absent in minimal fixture only'),
]


# ============================================================
# Helpers
# ============================================================

def _parse_header_cols(header_line):
    """Extract column names from a pipe-table header line.

    '| Col1 | Col2 | Col3 |' -> ['Col1', 'Col2', 'Col3']
    """
    if not header_line:
        return []
    parts = header_line.strip().split('|')
    return [p.strip() for p in parts if p.strip()]


def _grammar_key(blk):
    """Resolve the TABLE_GRAMMAR lookup key for a block."""
    if blk.get('type') == 'financial_table':
        return blk.get('table_type', 'financial_table')
    if blk.get('type') == 'metric_table':
        return 'metric_status'
    return blk.get('type', '')


def _find_suppression(rule_id, gkey):
    """Return (decision_num, reason) if suppressed, else None."""
    for dnum, gk, rid, reason in _SUPPRESSION_REGISTRY:
        if rid == rule_id and gk == gkey:
            return (dnum, reason)
    return None


def _maybe_suppress(findings, rule_id, severity, block_id, message, gkey):
    """Append a finding, relabeling to I1/INFO if suppressed."""
    sup = _find_suppression(rule_id, gkey)
    if sup:
        dnum, reason = sup
        findings.append(Finding(
            'I1', 'INFO', block_id,
            f'[{rule_id}] {message} [suppressed: #{dnum} — {reason}]',
            decision_num=dnum,
        ))
    else:
        findings.append(Finding(
            rule_id, severity, block_id, message, decision_num=None))


# ============================================================
# Per-block render-IR lint rules
# ============================================================

def _rule_b1_unknown_type(blk, findings):
    """B1: unknown block type -> BLOCKER."""
    btype = blk.get('type')
    if btype not in ALLOWED_BLOCK_TYPES:
        findings.append(Finding(
            'B1', 'BLOCKER', blk.get('id', '??'),
            f'Unknown block type: {btype!r}',
            decision_num=None))


def _rule_b2_table_in_prose(blk, findings):
    """B2 partial: pipe-table pattern in prose block -> WARNING.

    Render-IR level only: checks for '|'-delimited lines.
    Full HTML-level check is a # PHASE 3b stub.
    """
    if blk.get('type') != 'prose':
        return
    for line in blk.get('lines', []):
        s = line.strip()
        if s.startswith('|') and s.endswith('|') and s.count('|') >= 3:
            findings.append(Finding(
                'B2', 'WARNING', blk.get('id', '??'),
                'Pipe-table pattern in prose block — possible un-migrated table',
                decision_num=None))
            return  # one per block


def _rule_e1_column_order(blk, findings):
    """E1: semantic-header column order mismatch -> ERROR.

    Positional tables (#15): anchor-based relative-order check.
    Strict tables: exact column-name match at each position.
    Extra appended columns -> I2 (INFO).
    Prepended # row-number -> I3 (INFO, decision #16).
    """
    if 'header' not in blk:
        return
    gkey = _grammar_key(blk)
    grammar = TABLE_GRAMMAR.get(gkey)
    if not grammar or not grammar.get('strict_order'):
        return

    actual = _parse_header_cols(blk['header'])
    if not actual:
        return

    expected = grammar['columns']
    bid = blk.get('id', '??')

    # ---- I3: prepended # row-number column ----
    cols = list(actual)
    if cols and cols[0] == '#':
        findings.append(Finding(
            'I3', 'INFO', bid,
            'Row-number column (#) prepended before first §3 column',
            decision_num=16))
        cols = cols[1:]

    if grammar.get('positional'):
        # ---- Anchor-based relative-order check ----
        anchors = grammar.get('anchors', {})
        anchor_actual = {}  # schema_pos -> actual_pos
        for schema_pos, pattern in sorted(anchors.items()):
            for i, col in enumerate(cols):
                if re.search(pattern, col):
                    anchor_actual[schema_pos] = i
                    break
            else:
                _maybe_suppress(findings, 'E1', 'ERROR', bid,
                    f'Anchor column for §3 position {schema_pos} '
                    f'(pattern {pattern!r}) not found in header: {cols}',
                    gkey)
        # Verify relative order of found anchors
        prev_actual = -1
        for sp in sorted(anchor_actual.keys()):
            ap = anchor_actual[sp]
            if ap <= prev_actual:
                _maybe_suppress(findings, 'E1', 'ERROR', bid,
                    f'Anchor columns in wrong relative order — '
                    f'scrambled column order detected (§3 pos {sp} '
                    f'at actual col {ap}, expected after col {prev_actual})',
                    gkey)
            prev_actual = ap
    else:
        # ---- Strict name-match check ----
        # I2: extra appended columns
        extra = len(cols) - len(expected)
        if extra > 0:
            extras = cols[len(expected):]
            findings.append(Finding(
                'I2', 'INFO', bid,
                f'{extra} extra column(s) appended: {extras}',
                decision_num=None))
            core = cols[:len(expected)]
        else:
            core = cols

        # E1: exact name at each position
        for i in range(min(len(core), len(expected))):
            if core[i] != expected[i]:
                _maybe_suppress(findings, 'E1', 'ERROR', bid,
                    f'Column {i}: expected {expected[i]!r}, '
                    f'got {core[i]!r}',
                    gkey)


def _rule_e2_missing_columns(blk, findings):
    """E2: fewer columns than grammar requires -> ERROR.

    Skipped for positional grammars (Tier 2 tables have variable
    column counts by design — #20-24).
    """
    if 'header' not in blk:
        return
    gkey = _grammar_key(blk)
    grammar = TABLE_GRAMMAR.get(gkey)
    if not grammar or not grammar.get('columns') or grammar.get('positional'):
        return

    actual = _parse_header_cols(blk['header'])
    if actual and actual[0] == '#':
        actual = actual[1:]

    expected = grammar['columns']
    if len(actual) < len(expected):
        missing = len(expected) - len(actual)
        _maybe_suppress(findings, 'E2', 'ERROR', blk.get('id', '??'),
            f'{missing} column(s) fewer than §3 grammar '
            f'(have {len(actual)}, need {len(expected)})',
            gkey)


def _rule_e3_details_in_block(blk, findings):
    """E3 partial: <details> inside block content -> BLOCKER.

    Render-IR level: scans block lines, rows, header, text fields.
    Full HTML-level scan is a # PHASE 3b stub.
    """
    bid = blk.get('id', '??')
    # Lines (prose, coach_card, appendix_hand)
    for line in blk.get('lines', []):
        if '<details' in line.lower() or '</details' in line.lower():
            findings.append(Finding(
                'E3', 'BLOCKER', bid,
                '<details> tag inside block boundary — HARD GATE violation',
                decision_num=None))
            return
    # Rows (table blocks)
    for row in blk.get('rows', []):
        if isinstance(row, str) and ('<details' in row.lower()
                                      or '</details' in row.lower()):
            findings.append(Finding(
                'E3', 'BLOCKER', bid,
                '<details> tag inside table row — HARD GATE violation',
                decision_num=None))
            return
    # Header / separator / text (defensive)
    for field in ('header', 'separator', 'text'):
        val = blk.get(field, '')
        if isinstance(val, str) and '<details' in val.lower():
            findings.append(Finding(
                'E3', 'BLOCKER', bid,
                f'<details> tag inside block {field} — HARD GATE violation',
                decision_num=None))
            return


def _rule_e4_empty_rows(blk, findings):
    """E4: empty rows list in table block -> ERROR."""
    _TABLE_TYPES_WITH_ROWS = {
        'financial_table', 'hand_evidence_table', 'variance_ledger',
        'leak_bucket_overview', 'profile_matrix', 'action_review',
        'raw_reference',
    }
    if blk.get('type') not in _TABLE_TYPES_WITH_ROWS:
        return
    if not blk.get('rows'):
        gkey = _grammar_key(blk)
        _maybe_suppress(findings, 'E4', 'ERROR', blk.get('id', '??'),
            f'Empty rows list in {blk["type"]} block',
            gkey)


def _rule_e5_separator_mismatch(blk, findings):
    """E5: separator column count != header column count -> ERROR."""
    if 'header' not in blk or 'separator' not in blk:
        return
    hcols = _parse_header_cols(blk['header'])
    scols = _parse_header_cols(blk['separator'])
    if len(scols) != len(hcols):
        gkey = _grammar_key(blk)
        _maybe_suppress(findings, 'E5', 'ERROR', blk.get('id', '??'),
            f'Separator has {len(scols)} columns but header has '
            f'{len(hcols)}',
            gkey)


def _rule_w1_wide_table(blk, findings):
    """W1: table with >8 columns -> WARNING."""
    if 'header' not in blk:
        return
    ncols = len(_parse_header_cols(blk['header']))
    if ncols > 8:
        findings.append(Finding(
            'W1', 'WARNING', blk.get('id', '??'),
            f'Wide table: {ncols} columns (>8 threshold)',
            decision_num=None))


# ============================================================
# Phase 3b stubs — HTML-level rules
# ============================================================

def _rule_b3_contrast(blk, findings):
    """B3 — Pattern-match known low-contrast combinations.

    Phase 4.5 activation (was Phase 3b stub). Checks for:
      - Inline styles with light background + white/light text
      - Known-bad class combinations (highlight rows with light text)
      - Yellow/light backgrounds with white (#fff*) text

    Severity: WARNING. This is a pattern-match guard, not a full WCAG
    contrast-ratio audit.
    """
    import re
    block_id = blk.get('id', '') or blk.get('block_id', '')

    # Gather all text content from the block
    all_lines = []
    for key in ('raw_lines', 'lines'):
        val = blk.get(key, [])
        if isinstance(val, list):
            all_lines.extend(val)
    # Also check row cells
    for row in blk.get('rows', []):
        if isinstance(row, (list, tuple)):
            all_lines.extend(str(c) for c in row)

    # Pattern-match known bad contrast combinations in inline styles
    _BAD_PATTERNS = [
        # light background (#e…, #f…) paired with white text
        (re.compile(r'background\s*:\s*#(?:f[0-9a-f]{5}|ff[0-9a-f]{4}'
                    r'|[eE][0-9a-f]{5})[^;]*;\s*color\s*:\s*#(?:fff\b|ffffff)',
                    re.IGNORECASE),
         'light background with white text'),
        # yellow/amber background with white text (named or hex)
        (re.compile(r'background\s*:\s*(?:yellow|#ff[fed][0-9a-f]{0,3}|'
                    r'#fef[0-9a-f]{0,3})[^;]*;\s*color\s*:\s*#(?:fff\b|ffffff)',
                    re.IGNORECASE),
         'yellow background with white text'),
    ]

    for line in all_lines:
        if not isinstance(line, str):
            continue
        for pat, desc in _BAD_PATTERNS:
            if pat.search(line):
                findings.append(Finding(
                    'B3', 'WARNING', block_id,
                    'Low-contrast pattern: {} in block {}'.format(desc, block_id),
                    decision_num=None))


def _stub_e3_html_details(blk, findings):
    """# PHASE 3b STUB: E3 full — <details> in rendered HTML.

    Partial render-IR check is in _rule_e3_details_in_block above.
    Full Phase 3b will scan rendered HTML output.
    """
    pass


def _stub_e6_html_anchors(blk, findings):
    """# PHASE 3b STUB: E6 full — duplicate HTML anchor IDs.

    Render-IR duplicate block-ID check is in _registry_e6 below.
    Full Phase 3b will check <h2 id="...">, <a id="...">, etc.
    """
    pass


def _stub_w2_inline_html(blk, findings):
    """# PHASE 3b STUB: W2 — raw HTML in table rows -> WARNING.

    Will check table rows for HTML tags other than known-safe
    card pills and hand-net spans.
    """
    pass


# ============================================================
# Registry-level / cross-cutting rules (run once per render)
# ============================================================

def _rule_b4_orphan_pills(findings):
    """B4: every cited hand must have a corresponding appendix card -> BLOCKER.

    Phase 4.5 universal-pill guarantee (spec §3).  Reads the citation
    registry and appendix-hand-id set from _state.  Fires once per
    orphan hand_id.

    Skips when either set is empty — that means the linter is being
    called on a standalone Doc, not after a full _build() render pipeline.
    """
    from gem_report_draft import _state
    cited = set(_state._CITATIONS.keys())
    appendix = set(_state._APPENDIX_HAND_IDS)
    if not cited or not appendix:
        return  # no full render context — nothing to validate
    # v8.8.7: budget-trimmed hands are an intentional appendix drop, not an
    # orphan — they render with a 'budget_trimmed' availability fallback.
    trimmed = set(getattr(_state, '_BUDGET_TRIMMED_IDS', set()) or set())
    orphans = cited - appendix - trimmed
    for hid in sorted(orphans):
        findings.append(Finding(
            'B4', 'BLOCKER', '',
            f'Orphan pill: hand {hid} cited but no appendix card exists',
            decision_num=None))


def _registry_e6_duplicate_ids(registry, findings):
    """E6: duplicate block IDs across registry -> ERROR.

    Render-IR level check. Full HTML anchor uniqueness is Phase 3b.
    """
    seen = {}
    for entry in registry:
        blk = entry['block']
        bid = blk.get('id', '')
        if not bid:
            continue
        if bid in seen:
            findings.append(Finding(
                'E6', 'ERROR', bid,
                f'Duplicate block ID: {bid!r} '
                f'(first seen at line {seen[bid]})',
                decision_num=None))
        else:
            seen[bid] = entry.get('start_line', '?')


# ============================================================
# Main linter entry point
# ============================================================

def _rule_board_contradictions(stats, report_data, findings):
    """B-BOARD: cross-check analyst arguments against board_state (v8.7.7).

    Checks for flush/straight completion claims that contradict the
    computed board state. ERROR severity (factual, binary).
    """
    analyst_pre = (report_data.get('analyst_commentary') or {})
    if not isinstance(analyst_pre, dict):
        return

    # Flush-completion keywords
    _FLUSH_PHRASES = re.compile(
        r'flush[- ]complet|flush gets there|third (heart|spade|diamond|club)|'
        r'brings the flush|flush[- ]completing (river|turn)',
        re.IGNORECASE)

    # Straight-completion keywords
    _STRAIGHT_PHRASES = re.compile(
        r'straight[- ]complet|straight gets there|brings the straight|'
        r'straight[- ]completing (river|turn)',
        re.IGNORECASE)

    hands_by_id = {}
    for h in (stats.get('_hands_ref') or []):
        if isinstance(h, dict) and h.get('id'):
            hands_by_id[h['id']] = h

    for hid, entry in analyst_pre.items():
        if hid == '__synthesis__' or not isinstance(entry, dict):
            continue
        argument = entry.get('argument', '') or ''
        if not argument:
            continue

        # Get board_state for this hand
        h = hands_by_id.get(hid) or hands_by_id.get(f'TM{hid}') or {}
        board = h.get('board', [])
        if not board or len(board) < 3:
            continue

        try:
            from gem_board_state import board_state as _bs_fn
            bs = _bs_fn(board)
        except Exception:
            continue

        # Check flush contradiction
        if _FLUSH_PHRASES.search(argument):
            any_flush_completed = any(
                bs.get(st, {}).get('flush_completed_this_street', False)
                for st in ('turn', 'river'))
            if not any_flush_completed:
                board_str = ' '.join(board)
                findings.append(Finding(
                    rule='B-BOARD-FLUSH',
                    severity='ERROR',
                    block_id=hid,
                    message=f'argument claims a flush completed but board_state shows '
                            f'no flush completion (board: {board_str})',
                    decision_num=None))

        # Check straight contradiction
        if _STRAIGHT_PHRASES.search(argument):
            any_straight_completed = any(
                'completed' in (bs.get(st, {}).get('straight_status', '') or '')
                for st in ('turn', 'river'))
            if not any_straight_completed:
                board_str = ' '.join(board)
                findings.append(Finding(
                    rule='B-BOARD-STRAIGHT',
                    severity='ERROR',
                    block_id=hid,
                    message=f'argument claims a straight completed but board_state shows '
                            f'no straight completion (board: {board_str})',
                    decision_num=None))


def lint_doc(doc):
    """Run all 15 lint rules against a Doc's block registry + state.

    Returns list[Finding] sorted by severity (BLOCKER first) then rule.
    """
    findings = []
    registry = getattr(doc, '_block_registry', [])

    # Per-block rules
    for entry in registry:
        blk = entry['block']
        _rule_b1_unknown_type(blk, findings)
        _rule_b2_table_in_prose(blk, findings)
        _rule_e1_column_order(blk, findings)
        _rule_e2_missing_columns(blk, findings)
        _rule_e3_details_in_block(blk, findings)
        _rule_e4_empty_rows(blk, findings)
        _rule_e5_separator_mismatch(blk, findings)
        _rule_w1_wide_table(blk, findings)
        # Phase 3b stubs (no-ops — declared for visibility)
        _rule_b3_contrast(blk, findings)
        _stub_e3_html_details(blk, findings)
        _stub_e6_html_anchors(blk, findings)
        _stub_w2_inline_html(blk, findings)

    # Registry-level / cross-cutting rules
    _registry_e6_duplicate_ids(registry, findings)
    _rule_b4_orphan_pills(findings)

    # Sort: BLOCKER > ERROR > WARNING > INFO, then rule, then block_id
    _SEV = {'BLOCKER': 0, 'ERROR': 1, 'WARNING': 2, 'INFO': 3}
    findings.sort(key=lambda f: (_SEV.get(f.severity, 9), f.rule,
                                  f.block_id or ''))
    return findings


# ============================================================
# Output helpers
# ============================================================

def counts(findings):
    """Return (blocker, error, warning, info) counts."""
    c = {'BLOCKER': 0, 'ERROR': 0, 'WARNING': 0, 'INFO': 0}
    for f in findings:
        c[f.severity] = c.get(f.severity, 0) + 1
    return c['BLOCKER'], c['ERROR'], c['WARNING'], c['INFO']


def format_console_summary(findings):
    """One-line console summary + per-finding detail for ERROR/BLOCKER."""
    b, e, w, i = counts(findings)
    lines = [f"gem_report_lint: {b} BLOCKER · {e} ERROR "
             f"· {w} WARNING · {i} INFO"]
    for f in findings:
        if f.severity in ('ERROR', 'BLOCKER'):
            bid = f.block_id or '—'
            lines.append(f"  LINT: {f.rule} | {bid} | {f.message}")
    return '\n'.join(lines)


def format_qa_block(findings):
    """Collapsed HTML lines for post-appendix QA section.

    Returns list[str] suitable for doc.w() calls.
    """
    b, e, w, i = counts(findings)
    tag = (f"{b} BLOCKER · {e} ERROR "
           f"· {w} WARNING · {i} INFO")
    lines = [
        '',
        f'<details class="qa-lint">',
        f'<summary>\U0001f50d QA Lint Report ({tag})</summary>',
        '',
        '| Rule | Severity | Block ID | Message |',
        '|---|---|---|---|',
    ]
    for f in findings:
        esc = f.message.replace('|', '\\|')
        bid = (f.block_id or '—').replace('|', '\\|')
        lines.append(f'| {f.rule} | {f.severity} | {bid} | {esc} |')
    lines.append('')
    lines.append('</details>')
    lines.append('')
    return lines


# ============================================================
# Orchestration helper — called by draft.py
# ============================================================

def lint_and_gate(doc, strict_lint=False, qa_block=False,
                  stats=None, report_data=None):
    """Run lint, print console summary, optionally append QA block.

    Returns list[Finding].
    Raises SystemExit if strict_lint and BLOCKER count > 0.
    """
    findings = lint_doc(doc)
    # v8.7.7: board contradiction lint (needs stats + report_data)
    if stats and report_data:
        _rule_board_contradictions(stats, report_data, findings)
    print(format_console_summary(findings))
    if qa_block:
        for line in format_qa_block(findings):
            doc.w(line)
    if strict_lint:
        b, _, _, _ = counts(findings)
        if b > 0:
            raise SystemExit(
                f"gem_report_lint: {b} BLOCKER(s) — "
                f"aborting (--strict-lint)")
    return findings
