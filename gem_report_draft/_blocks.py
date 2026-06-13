"""Render-IR block types, factory functions, and block-to-lines renderer.

Phase 1 (P1): blocks render to the SAME markdown lines the current doc.w()
emitters produce.  No section emitter is migrated yet — this module proves
the block→lines equivalence so that P2 migration can proceed table-by-table.

Block types (strict — §2 of GEM_Report_Redesign_Implementation_Handoff.md):

    coach_card          metric_table        hand_evidence_table
    financial_table     variance_ledger     leak_bucket_overview
    profile_matrix      action_review       method_note
    review_control      appendix_hand       prose          heading
"""

# ============================================================
# Allowed block types — lint (Phase 3) rejects unknowns
# ============================================================

ALLOWED_BLOCK_TYPES = frozenset({
    'coach_card', 'metric_table', 'hand_evidence_table', 'financial_table',
    'variance_ledger', 'leak_bucket_overview', 'profile_matrix', 'action_review',
    'raw_reference', 'method_note', 'review_control', 'appendix_hand',
    'prose', 'heading',
})


# ============================================================
# Factory functions
# ============================================================

def heading_block(block_id, level, anchor, header, summary):
    """Heading block — section (level=1) or subsection (level=2).

    NOT rendered by _block_to_lines — heading blocks require Doc state
    management (TOC entries, review-row tracking, citation section
    tracking) and must be dispatched to Doc.section()/subsection()
    by the calling code.
    """
    return {
        'type': 'heading', 'id': block_id,
        'level': level, 'anchor': anchor,
        'header': header, 'summary': summary,
    }


def prose_block(block_id, lines):
    """Raw markdown passthrough — escape hatch for incremental migration.

    Phase 3 lint WARNs on any prose block containing '|' (un-migrated table).
    """
    return {'type': 'prose', 'id': block_id, 'lines': list(lines)}


def method_note_block(block_id, text):
    """Methodology / caveat footnote — italic text + trailing blank line."""
    return {'type': 'method_note', 'id': block_id, 'text': text}


def review_control_block(block_id, rtype, anchor, title):
    """Audit review control (B168 sentinel).

    rtype: 'sub' (3 verdicts) | 'hand' (5 verdicts, adds GTOW options).
    """
    return {
        'type': 'review_control', 'id': block_id,
        'rtype': rtype, 'anchor': anchor, 'title': title,
    }


def metric_table_block(block_id, rows):
    """Metric-status table — §3 metric_status grammar.

    Columns: Metric | Status | Value/Rate ⓘ | Target | Delta | Sample | Notes

    Each row is EITHER:
      • a dict (rendered via _stat_row / _stat_row_pct):
            name       : str   — metric label
            x          : int   — numerator (successes)
            n          : int   — denominator (opportunities)
            target_lo  : float — target range low bound (%)
            target_hi  : float — target range high bound (%)
            notes      : str   — optional notes column text (default '')
            n_min      : int   — minimum n for signal (default 10)
            link_to    : str   — optional section anchor for metric name link
            aim        : str   — optional watchlist-derived aim annotation
            pct_mode   : bool  — when True, use _stat_row_pct (pct + n, no x)
            pct        : float — percentage when pct_mode=True
      • a str (raw pre-formatted pipe-table row, passed through verbatim).
            Used for manual rows with custom computation (VPIP dynamic
            targets, AF/AFq derived ratios, informational sub-rows).

    Header and separator are always canonical (from Doc.STAT_HEADER/STAT_SEP)
    — single source of truth for lint validation.
    """
    from gem_report_draft._html import Doc
    return {
        'type': 'metric_table', 'id': block_id, 'rows': list(rows),
        'header': Doc.STAT_HEADER,
        'separator': Doc.STAT_SEP,
    }


def financial_table_block(block_id, table_type, header, separator, rows):
    """Financial table (daily summary, tournament PnL, etc.).

    table_type : str  — 'financial_summary' | 'tournament_pnl'
    header     : str  — exact pipe-table header line
    separator  : str  — exact pipe-table separator line
    rows       : list[str] — pre-formatted pipe-table row strings
    """
    return {
        'type': 'financial_table', 'id': block_id,
        'table_type': table_type,
        'header': header, 'separator': separator, 'rows': list(rows),
    }


def hand_evidence_table_block(block_id, header, separator, rows):
    """Hand-evidence table (III.1 mistakes, I.3 Large-Loss Audit, etc.).

    header    : str       — exact pipe-table header line
    separator : str       — exact pipe-table separator line
    rows      : list[str] — pre-formatted pipe-table row strings
    """
    return {
        'type': 'hand_evidence_table', 'id': block_id,
        'header': header, 'separator': separator, 'rows': list(rows),
    }


def variance_ledger_block(block_id, header, separator, rows):
    """Variance ledger table (all-ins, made-hands vs expected).

    header    : str       — exact pipe-table header line
    separator : str       — exact pipe-table separator line
    rows      : list[str] — pre-formatted pipe-table row strings
    """
    return {
        'type': 'variance_ledger', 'id': block_id,
        'header': header, 'separator': separator, 'rows': list(rows),
    }


def leak_bucket_overview_block(block_id, header, separator, rows):
    """Strategic leak bucket overview table (III.3).

    header    : str       — exact pipe-table header line
    separator : str       — exact pipe-table separator line
    rows      : list[str] — pre-formatted pipe-table row strings
    """
    return {
        'type': 'leak_bucket_overview', 'id': block_id,
        'header': header, 'separator': separator, 'rows': list(rows),
    }


def profile_matrix_block(block_id, header, separator, rows):
    """Position / segment profile matrix table (V/VI/VII).

    header    : str       — exact pipe-table header line
    separator : str       — exact pipe-table separator line
    rows      : list[str] — pre-formatted pipe-table row strings
    """
    return {
        'type': 'profile_matrix', 'id': block_id,
        'header': header, 'separator': separator, 'rows': list(rows),
    }


def action_review_block(block_id, header, separator, rows):
    """Bet / check decision review table (VIII).

    header    : str       — exact pipe-table header line
    separator : str       — exact pipe-table separator line
    rows      : list[str] — pre-formatted pipe-table row strings
    """
    return {
        'type': 'action_review', 'id': block_id,
        'header': header, 'separator': separator, 'rows': list(rows),
    }


def raw_reference_block(block_id, header, separator, rows):
    """Raw reference table (XIII — Full Deviation Lists / Raw Stats).

    §3: source order allowed; lint checks for visible
    "Raw reference" tag (Phase 3). Column order is NOT grammar-enforced.

    header    : str       — exact pipe-table header line
    separator : str       — exact pipe-table separator line
    rows      : list[str] — pre-formatted pipe-table row strings
    """
    return {
        'type': 'raw_reference', 'id': block_id,
        'header': header, 'separator': separator, 'rows': list(rows),
    }


def coach_card_block(block_id, lines):
    """Coach card — TL;DR narrative bullets and structured prose."""
    return {'type': 'coach_card', 'id': block_id, 'lines': list(lines)}


def appendix_hand_block(block_id, lines):
    """Appendix hand replay block (hand-grid HTML + analyst notes div)."""
    return {'type': 'appendix_hand', 'id': block_id, 'lines': list(lines)}


# ============================================================
# Block → lines renderer
# ============================================================

def _block_to_lines(blk):
    """Render a block dict to a list of markdown-line strings.

    Phase 1: produces the EXACT same lines as the current emitters.
    The 'heading' type requires Doc state (TOC, review tracking, citation
    section) and must be dispatched to Doc.section()/subsection() by the
    caller — _block_to_lines with a heading block raises ValueError.
    """
    btype = blk.get('type')
    if btype not in ALLOWED_BLOCK_TYPES:
        raise ValueError(f"Unknown block type: {btype!r}")
    if btype == 'heading':
        raise ValueError(
            "heading blocks require Doc state management — dispatch "
            "to Doc.section()/subsection(), not _block_to_lines()"
        )
    renderer = _RENDERERS.get(btype)
    if renderer is None:
        raise ValueError(f"No renderer registered for block type: {btype!r}")
    return renderer(blk)


# ---- metric_table: structured rows → _stat_row helpers ----

def _render_metric_table(blk):
    """Render metric_table block to header + separator + stat rows.

    Rows may be dicts (rendered via helpers) or raw strings (passthrough).
    Header/separator come from the block (set by constructor from
    Doc.STAT_HEADER/STAT_SEP — single source of truth).
    """
    from gem_report_draft._helpers import _stat_row, _stat_row_pct
    lines = [blk['header'], blk['separator']]
    for row in blk.get('rows', []):
        if isinstance(row, str):
            # Raw pre-formatted pipe-table row — passthrough
            lines.append(row)
        elif row.get('pct_mode'):
            lines.append(_stat_row_pct(
                row['name'], row['pct'], row['n'],
                row['target_lo'], row['target_hi'],
                notes=row.get('notes', ''),
                n_min=row.get('n_min', 10),
                link_to=row.get('link_to'),
                aim=row.get('aim'),
            ))
        else:
            lines.append(_stat_row(
                row['name'], row['x'], row['n'],
                row['target_lo'], row['target_hi'],
                notes=row.get('notes', ''),
                n_min=row.get('n_min', 10),
                link_to=row.get('link_to'),
                aim=row.get('aim'),
            ))
    return lines


# ---- Generic table: header + separator + pre-formatted rows ----

def _render_generic_table(blk):
    """Render a table block whose rows are pre-formatted pipe-table strings."""
    lines = [blk['header'], blk['separator']]
    lines.extend(blk.get('rows', []))
    return lines


# ---- Simple block types ----

def _render_prose(blk):
    """Passthrough — returns the block's lines verbatim."""
    return list(blk.get('lines', []))


def _render_method_note(blk):
    """Italic method/caveat text followed by a blank line."""
    return [blk['text'], '']


def _render_review_control(blk):
    """B168 audit review sentinel line."""
    return [f"<<REVIEWROW|{blk['rtype']}|{blk['anchor']}|{blk['title']}>>"]


def _render_coach_card(blk):
    """Coach card — passthrough of structured narrative lines."""
    return list(blk.get('lines', []))


def _render_appendix_hand(blk):
    """Appendix hand — passthrough of hand-grid + notes lines."""
    return list(blk.get('lines', []))


# ---- Dispatch table ----
# 'heading' is intentionally absent — caller dispatches to Doc.section()/subsection().

_RENDERERS = {
    'metric_table':         _render_metric_table,
    'financial_table':      _render_generic_table,
    'hand_evidence_table':  _render_generic_table,
    'variance_ledger':      _render_generic_table,
    'leak_bucket_overview': _render_generic_table,
    'profile_matrix':       _render_generic_table,
    'action_review':        _render_generic_table,
    'raw_reference':        _render_generic_table,
    'method_note':          _render_method_note,
    'review_control':       _render_review_control,
    'prose':                _render_prose,
    'coach_card':           _render_coach_card,
    'appendix_hand':        _render_appendix_hand,
}
