"""gem_review_trust.py — Review Precision & Decision-Trust helpers (v8.16.4).

PURE, renderer-layer helpers that make the primary review queue and the per-hand
verdicts trustworthy. They:

  * invent no poker analysis and RE-GRADE nothing;
  * contain NO rules keyed to any real hand / tournament / player / session id —
    every function takes explicit primitive inputs;
  * are exercised entirely by synthetic fixtures (T-RPDT-* in _test_scratch.py).

Each helper encodes ONE contract from the Review-Precision/Decision-Trust batch:

  build_why_review / is_generic_reason   -> Objective 4 (actionable "why this hand")
  reconcile_verdict / verdict_marker_*   -> Objective 5 (verdict/action reconciliation)
  allin_math_kind / required_allin_fields-> Objective 7 (all-in decision math)
  multiway_render_plan                   -> Objective 8 (multiway snapshot, no HU math)
  bounty_provenance_label                -> Objective 9 (PKO bounty provenance)
  attribution_label / attribution_plan   -> Objective 11 (root vs downstream vs result)

Range-domain helpers (Objectives 6 + 10) live in gem_ranges.py (range_highlight*,
the villain-focused postflop lens) because they belong to the range model.
"""

# ============================================================
# Objective 4 — actionable "why this hand"
# ============================================================
# Generic copy that may NEVER be the complete explanation for a primary review
# item (compared case-insensitively against the stripped reason text).
GENERIC_REVIEW_PHRASES = frozenset({
    'strategic leak', 'strategic leak.',
    'known leak', 'known leak.',
    'potential detector blind spot', 'potential detector blind spot.',
    'spots cleared or monitored', 'spots cleared or monitored.',
    'detector blind spot', 'blind spot', 'blind-spot sample',
    'marginal candidate', 'marginal candidate.',
    'auto clear', 'auto-clear', 'auto-cleared',
    'review', 'review.', 'leak', 'mistake', 'candidate',
})

REVIEW_CATEGORIES = (
    'confirmed_mistake', 'candidate', 'strategic_debate',
    'trust_inconsistency', 'representative_leak',
)

_CATEGORY_LABEL = {
    'confirmed_mistake': 'Confirmed mistake',
    'candidate': 'Candidate',
    'strategic_debate': 'Strategic debate',
    'trust_inconsistency': 'Trust inconsistency',
    'representative_leak': 'Representative leak example',
}

_VALID_STREETS = ('preflop', 'flop', 'turn', 'river')


def is_generic_reason(text):
    """True when ``text`` is empty or is ONLY a banned generic phrase (i.e. it
    carries no concrete content). A reason that merely CONTAINS a generic word
    but also names a street/action/number is NOT generic."""
    if not text:
        return True
    t = ' '.join(str(text).split()).strip().lower().rstrip('.')
    if not t:
        return True
    if (t in GENERIC_REVIEW_PHRASES) or (t + '.') in GENERIC_REVIEW_PHRASES:
        return True
    # also catch the bare generic phrase with trailing punctuation/words removed
    return t in {p.rstrip('.') for p in GENERIC_REVIEW_PHRASES}


def build_why_review(street, hero_action, reason, category):
    """Build the actionable 'why this hand' contract for a primary review item.

    Returns a dict {street, action, reason, category, category_label, why} or
    ``None`` when the item is NOT admissible to the primary queue (missing
    street/action, unknown category, or a generic-only reason). A None return is
    the gate: "if no concrete reason exists, the hand must not enter the primary
    queue."
    """
    st = (street or '').strip().lower()
    act = ' '.join((hero_action or '').split()).strip()
    rsn = ' '.join((reason or '').split()).strip()
    if st not in _VALID_STREETS:
        return None
    if not act:
        return None
    if category not in REVIEW_CATEGORIES:
        return None
    if is_generic_reason(rsn):
        return None
    return {
        'street': st,
        'action': act,
        'reason': rsn,
        'category': category,
        'category_label': _CATEGORY_LABEL[category],
        'why': '%s: %s — %s' % (st.capitalize(), act, rsn),
    }


def actionable_reason_ok(why):
    """Validator: a primary-queue item must carry a non-generic, fully-specified
    'why' (street + action + concrete reason + valid category)."""
    if not isinstance(why, dict):
        return False
    return (why.get('street') in _VALID_STREETS
            and bool((why.get('action') or '').strip())
            and not is_generic_reason(why.get('reason'))
            and why.get('category') in REVIEW_CATEGORIES)


# ============================================================
# Objective 5 — verdict/action reconciliation invariant
# ============================================================
# A hand-level verdict must reconcile with action-level evidence.
MISTAKE_VERDICTS = frozenset({'mistake', 'punt', 'key mistake'})
NON_MISTAKE_VERDICTS = frozenset({
    'justified', 'pick', 'cooler', 'read-dependent', 'read dependent',
    'cleared', 'review', 'debate',
})
REVIEW_FALLBACK = 'Review'


def _norm_verdict(v):
    return ' '.join(str(v or '').split()).strip().lower()


def is_mistake_verdict(verdict):
    return _norm_verdict(verdict) in MISTAKE_VERDICTS


def reconcile_verdict(verdict, has_bound_action_marker, has_explanation):
    """Reconcile a hand-level verdict with action-level evidence.

    Returns (final_verdict, scrub_negative_marker, reasons):

    * MISTAKE-class verdict that cannot point to a bound action-level negative
      marker AND a visible explanation -> downgraded to 'Review' (the report
      should not assert a Mistake it cannot locate). ``reasons`` explains why.
    * NON-MISTAKE verdict (Justified/Pick/Cooler/Read-Dependent/Cleared/...) ->
      ``scrub_negative_marker=True`` so any stale "Key mistake" tooltip / negative
      marker from an overridden earlier classification is removed.
    * Otherwise the verdict is preserved unchanged.

    Pure: callers pass booleans they already computed; this invents nothing.
    """
    reasons = []
    nv = _norm_verdict(verdict)
    if nv in MISTAKE_VERDICTS:
        if has_bound_action_marker and has_explanation:
            return (verdict, False, reasons)
        if not has_bound_action_marker:
            reasons.append('mistake verdict has no bound action-level marker')
        if not has_explanation:
            reasons.append('mistake verdict has no visible explanation')
        return (REVIEW_FALLBACK, False, reasons)
    if nv in NON_MISTAKE_VERDICTS:
        # non-mistake: drop any stale negative marker/tooltip from an override
        return (verdict, True, ['non-mistake verdict: scrub stale negative marker'])
    return (verdict, False, reasons)


def verdict_validation_issue(verdict, has_bound_action_marker, has_explanation):
    """Return a report-validator issue string if a Mistake verdict cannot be
    substantiated AND was not downgraded, else None. Used to fail/flag a build."""
    nv = _norm_verdict(verdict)
    if nv in MISTAKE_VERDICTS and not (has_bound_action_marker and has_explanation):
        return ('Mistake verdict not substantiated by a bound action-level '
                'marker + explanation (downgrade to Review)')
    return None


# ============================================================
# Objective 7 — preflop all-in decision math (by type)
# ============================================================
ALLIN_MATH_KINDS = ('call_vs_jam', 'open_shove', 'rejam', 'not_allin')

_REQUIRED_ALLIN_FIELDS = {
    'call_vs_jam': ('to_call', 'pot_before_call', 'required_equity',
                    'estimated_equity', 'chip_ev', 'bounty_adjusted'),
    'open_shove': ('hero_risk', 'pot_available', 'effective_stack',
                   'fold_equity_or_ev', 'equity_when_called', 'range_relationship',
                   'bounty_adjusted'),
    'rejam': ('hero_risk', 'pot_available', 'effective_stack',
              'fold_equity_or_ev', 'equity_when_called', 'range_relationship',
              'bounty_adjusted'),
}


def allin_math_kind(pf_allin, first_in, hero_aggressed, facing_allin):
    """Classify a preflop all-in decision for math rendering.

    * facing an all-in and calling it          -> 'call_vs_jam'
    * first-in shove (Hero opens all-in)        -> 'open_shove'
    * Hero jams over earlier aggression (re-jam) -> 'rejam'
    * not an all-in decision                     -> 'not_allin'
    """
    if not pf_allin:
        return 'not_allin'
    if facing_allin and not hero_aggressed:
        return 'call_vs_jam'
    if hero_aggressed and first_in:
        return 'open_shove'
    if hero_aggressed and not first_in:
        return 'rejam'
    return 'call_vs_jam' if facing_allin else 'open_shove'


def required_allin_fields(kind):
    """The decision-time arithmetic fields a render MUST show for this all-in
    type (drives a completeness check). Empty for 'not_allin'."""
    return _REQUIRED_ALLIN_FIELDS.get(kind, ())


def equity_label(is_heuristic):
    """Never claim exactness when the opponent range is heuristic; never use
    showdown/result equity as decision-time equity."""
    return 'estimated equity (heuristic range)' if is_heuristic else 'estimated equity'


# ============================================================
# Objective 8 — canonical multiway all-in snapshot
# ============================================================
def multiway_render_plan(n_live_opponents, players_still_to_act=0):
    """Decide how a multiway all-in must render (no heads-up math leaks).

    Returns a plan dict. With >=2 live opponents the single heads-up
    "Required equity: X%" line MUST be suppressed in favour of a field-equity
    view with one range line per live opponent; if players are still to act the
    pot odds are uncertain and must be marked as such.
    """
    n = max(0, int(n_live_opponents or 0))
    to_act = max(0, int(players_still_to_act or 0))
    is_multiway = n >= 2
    return {
        'is_multiway': is_multiway,
        'suppress_hu_required_equity': is_multiway,
        'show_field_equity': is_multiway,
        'per_opponent_range_lines': n if is_multiway else (1 if n == 1 else 0),
        'pot_odds_uncertain': to_act > 0,
        'label': ('Multiway all-in (%d-way)' % (n + 1)) if is_multiway else '',
    }


# ============================================================
# Objective 9 — PKO bounty provenance
# ============================================================
BOUNTY_PROVENANCE = ('exact', 'estimated', 'starting_bb_flat', 'effective_bb')


def bounty_provenance_label(kind, value_bb=None, value_usd=None):
    """Render-safe label that distinguishes how a bounty figure was derived, so
    a static event-level estimate is never displayed as if it were dynamic.

    * 'exact'           -> "Bounty: $X (exact)"
    * 'estimated'       -> "Estimated bounty: $X (~Y BB)"
    * 'starting_bb_flat'-> "Estimated bounty ~ Y starting BB — flat event estimate"
    * 'effective_bb'    -> "Bounty ~ Y BB at this decision (effective-stack)"
    """
    bb = ('%g' % value_bb) if value_bb is not None else '?'
    usd = ('$%s' % value_usd) if value_usd is not None else '$?'
    if kind == 'exact':
        return 'Bounty: %s (exact)' % usd
    if kind == 'estimated':
        return 'Estimated bounty: %s (~%s BB)' % (usd, bb)
    if kind == 'starting_bb_flat':
        return 'Estimated bounty ~ %s starting BB — flat event estimate' % bb
    if kind == 'effective_bb':
        return 'Bounty ~ %s BB at this decision (effective-stack)' % bb
    return 'Bounty value unavailable'


def bounty_is_dynamic(kind):
    """Only 'effective_bb' / 'exact' vary by decision; 'starting_bb_flat' and
    'estimated' are static and must be labelled as such (objective 9)."""
    return kind in ('effective_bb', 'exact')


# ============================================================
# Objective 11 — commentary attribution across streets
# ============================================================
ATTRIBUTION_ROLES = ('root_mistake', 'downstream', 'consequence', 'none')

_ATTRIBUTION_LABEL = {
    'root_mistake': 'root mistake',
    'downstream': 'downstream — compounds the earlier error',
    'consequence': 'result',
    'none': '',
}


def attribution_label(role):
    """Human label for a street's attribution role (structural support only —
    the analyst still authors the prose; this never invents content)."""
    return _ATTRIBUTION_LABEL.get(role, '')


def attribution_plan(roles_by_street):
    """Given {street: role}, return the ordered attribution plan and a flag for
    whether the full explanation would be duplicated (more than one street
    carrying the SAME non-'none' role beyond root) — which the renderer must
    avoid. Pure / structural; defaults make it a no-op when unused."""
    order = [s for s in _VALID_STREETS if (roles_by_street or {}).get(s) not in (None, 'none')]
    roles = [roles_by_street[s] for s in order]
    return {
        'streets': order,
        'roles': roles,
        'has_root': 'root_mistake' in roles,
        'has_downstream': 'downstream' in roles,
        # duplication smell: same explanation echoed on >1 street
        'duplicated': len(order) != len(set(order)),
    }
