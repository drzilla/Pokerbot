"""Shared mutable state for the gem_report_draft package.

Four rebindable module-level globals + six accessor functions. Every other
module in the package imports this MODULE OBJECT (never individual names)
so that rebindings via the accessor functions are visible everywhere.
"""

# --- Rebindable globals ---------------------------------------------------

_APPENDIX_HAND_IDS = set()
_APPENDIX_HAND_PRIORITIES = {}   # hid -> int (0=P0 must, 1=P1 should, 2=P2 optional, 3=P3 id-only)

_CITATIONS = {}
_CURRENT_SECTION_ANCHOR = None
_CURRENT_SECTION_LABEL = None
# v8.8.7: hands the HA3 budget planner intentionally trimmed from the appendix.
# Cited-but-trimmed hands degrade to handAvailability='budget_trimmed' (graceful
# popup fallback) and must be excluded from the B4 orphan-pill lint rule.
_BUDGET_TRIMMED_IDS = set()

# v8.16.2 (Phase B): 8-digit suffixes of every hand that actually received a FULL
# hand-detail card (XIV.A or XIV.B). XIV.C only emits a budget-trimmed STUB for a
# hand NOT in this set, so a hand can never render BOTH a full card and a stub
# (the "Issue 3" double-render). Populated at the full-card emit sites; read +
# filtered in the XIV.C stub loop. Render-level guarantee, independent of any
# upstream set-math gap in the HA3 budget planner.
_FULL_CARD_IDS = set()


# --- Accessors (the ONLY way to write these globals) -----------------------

def _set_appendix_hand_ids(ids):
    """Populate the module-level appendix-hand set. Called once per render."""
    global _APPENDIX_HAND_IDS, _APPENDIX_HAND_PRIORITIES
    _APPENDIX_HAND_IDS = set(ids) if ids else set()
    _APPENDIX_HAND_PRIORITIES = {}


def _register_hand_priority(hid, priority):
    """Record the priority of a hand for appendix inclusion.
    Keeps the BEST (lowest) priority if called multiple times for the same hid.
    0=P0 must, 1=P1 should, 2=P2 optional, 3=P3 id-only."""
    global _APPENDIX_HAND_PRIORITIES
    if hid in _APPENDIX_HAND_PRIORITIES:
        _APPENDIX_HAND_PRIORITIES[hid] = min(_APPENDIX_HAND_PRIORITIES[hid], priority)
    else:
        _APPENDIX_HAND_PRIORITIES[hid] = priority


def _set_current_section(anchor, label=None):
    """Called by Doc.subsection/section to update tracked context."""
    global _CURRENT_SECTION_ANCHOR, _CURRENT_SECTION_LABEL
    _CURRENT_SECTION_ANCHOR = anchor
    # B-V10: strip S-prefix from citation labels so backlinks read
    # "Large Losses ↑" not "S1.3 Large Losses ↑"
    import re
    _CURRENT_SECTION_LABEL = re.sub(r'^S\d+[\.\d]*\.?\s*', '', label) if label else label


def _record_citation(hand_id):
    """Register that hand_id was cited from the current section.
    Skips when current_section is None or is inside the appendix itself
    (no self-citation loops)."""
    global _CITATIONS
    if not hand_id or not _CURRENT_SECTION_ANCHOR:
        return
    if _CURRENT_SECTION_ANCHOR.startswith('sec-app-') or \
       _CURRENT_SECTION_ANCHOR == 'sec-18':
        return
    _CITATIONS.setdefault(hand_id, set()).add(
        (_CURRENT_SECTION_ANCHOR, _CURRENT_SECTION_LABEL or _CURRENT_SECTION_ANCHOR)
    )


def _reset_citations():
    """Clear citation registry — called at render start so state doesn't leak
    across multiple render calls in the same process."""
    global _CITATIONS, _CURRENT_SECTION_ANCHOR, _CURRENT_SECTION_LABEL
    global _APPENDIX_HAND_IDS, _APPENDIX_HAND_PRIORITIES
    global _BUDGET_TRIMMED_IDS, _FULL_CARD_IDS
    _CITATIONS = {}
    _CURRENT_SECTION_ANCHOR = None
    _CURRENT_SECTION_LABEL = None
    _APPENDIX_HAND_IDS = set()
    _APPENDIX_HAND_PRIORITIES = {}
    _BUDGET_TRIMMED_IDS = set()
    _FULL_CARD_IDS = set()


def _get_citations_for(hand_id):
    """Return sorted list of (anchor, label) tuples for a hand."""
    if hand_id not in _CITATIONS:
        return []
    return sorted(_CITATIONS[hand_id])


def _get_hands_for_section(section_anchor):
    """Return sorted list of hand_ids cited in the given section.

    Phase 4.5: inverse of _get_citations_for — used by the relevant-hands
    list popup (spec §2.2). Authoritative, registry-derived.
    """
    hands = []
    for hid, citations in _CITATIONS.items():
        if any(anchor == section_anchor for anchor, _ in citations):
            hands.append(hid)
    return sorted(hands)


def _record_citation_explicit(hand_id, anchor, label):
    """Register a citation with an EXPLICIT section anchor."""
    global _CITATIONS
    if not hand_id or not anchor:
        return
    _CITATIONS.setdefault(hand_id, set()).add((anchor, label or anchor))
