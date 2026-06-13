"""gem_report_draft package — split from the monolith gem_report_draft.py.

Public API (3 names imported by gem_analyzer.py):
    generate_report_draft, render_html, render_md

Internal names re-exported for test suite compatibility.
"""

from .draft import generate_report_draft, render_html, render_md, render_both

from ._helpers import (
    _wilson_ci, _clr, _clr_min, _stat_signal, _hand_ref,
    _compute_pot_by_street,
)

from ._html import _cards_str_to_pills

from ._state import (
    _reset_citations, _set_current_section, _record_citation, _get_citations_for,
)

from ._hand_grid import (
    _argument_is_structured, _key_decision_action_class,
    _parse_structured_argument, _pick_key_action_idx,
)
