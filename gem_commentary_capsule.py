"""v8.17 Epic A — Commentary capsule layer (v3.4 ROUTER_AWARE FINAL §9-§14).

PURE + synthetic-fixtured. This is the user-visible CAPSULE system that sits on top
of the v8.16.3 zero-drop migration AUDIT (gem_commentary_migration.py). It does three
things, all without touching the V25 router or any out-of-scope UI:

  1. REGISTER classification (§9): factual / coaching / no_clear_lesson.
  2. EVIDENCE-TIER wording gate (§10): chart-sourced / nearest-depth / constructed /
     villain-read / result-only — exact verbs allowed only on chart-sourced.
  3. CAPSULE assembly (§9 role set) — smallest useful prioritized role set, no empty
     roles, with a visible evidence anchor for every scored capsule (§11).

Plus the CONTENT lints the migration audit did not yet cover (§14):
  L1 verdict/range contradiction · L2 banned generic · L3 internal-token leak ·
  L6 terminal-result leakage · L7 factual praise/lesson · L9 missing register/tier ·
  L12 missing visible anchor · L13 result-only scored.

Invents no poker facts; consumes already-produced per-street signals. No real ids.
"""

REGISTERS = ('factual', 'coaching', 'no_clear_lesson')

# v8.18.0 Commentary Capsule: the CANONICAL contract register vocabulary. The internal classifier
# (classify_register) keeps its compact lower-case names; the canonical names are the user-/contract-
# facing vocabulary -- FACTUAL (what happened / what the evidence directly shows), COACHING (the
# practical lesson), INSUFFICIENT_EVIDENCE (explicitly what cannot safely be concluded, instead of a
# generic "Unclear"). One mapping, applied at build time, so no item is left unclassified.
CANONICAL_REGISTER = {
    'factual': 'FACTUAL',
    'coaching': 'COACHING',
    'no_clear_lesson': 'INSUFFICIENT_EVIDENCE',
}
CANONICAL_REGISTERS = ('FACTUAL', 'COACHING', 'INSUFFICIENT_EVIDENCE')


def canonical_register(*, verdict_class=None, gradeable=True, result_only=False, register=None):
    """Return the canonical contract register (FACTUAL | COACHING | INSUFFICIENT_EVIDENCE) for a
    commentary item -- the build-time classification every item carries. Pass an already-computed
    internal `register`, or the signals to classify. INSUFFICIENT_EVIDENCE is explicit, never a
    silent 'Unclear'."""
    internal = register or classify_register(
        verdict_class=verdict_class, gradeable=gradeable, result_only=result_only)
    return CANONICAL_REGISTER.get(internal, 'INSUFFICIENT_EVIDENCE')

# §10 evidence tiers, weakest-claim last.
EVIDENCE_TIERS = ('chart_sourced', 'nearest_depth', 'constructed',
                  'villain_read', 'result_only')

# Verbs/phrasings that assert chart-exact certainty — allowed ONLY on chart_sourced.
_EXACT_VERBS = (' is inside', ' is outside', 'is standard', 'exactly',
                'is in range', 'is a standard')

# §9 capsule roles, in display-priority order (smallest useful set; never all 8).
CAPSULE_ROLES = ('Decision', 'Verdict', 'Why', 'Math', 'Range',
                 'Exploit', 'Caveat', 'Consequence')

# §14 L2 — banned generic filler with no evidence content.
BANNED_GENERIC = (
    'nothing to fix', 'process and result agree', 'process and result aligned',
    'no notes', 'no comment', 'standard spot', 'nothing notable',
    'played fine', 'well played', 'good game',
)

# §14 L3 — internal / debug / schema / routing tokens that must never be user-visible.
INTERNAL_TOKENS = (
    'known_leak', 'auto_clear', 'flat_table', 'ratio_model',
    'detector blind spot', 'potential detector blind spot',
    'spots cleared or monitored', 'data-street', 'migration_status',
    'visible_capsule', 'more_payload', 'preserved_legacy', 'no_clear_lesson',
    'pko_context', 'bottomcontexts', 'coachingcards', 'handopponentcontexts',
    'decision_kind', 'pf_allin', 'required_eq_pct',
)

# §14 L6 — terminal/result/showdown language used AS the proof for Hero's DECISION.
# Deliberately narrow: only phrasings that justify the decision BY its outcome.
# Descriptive villain-range evidence ("Villain showed value via …") and neutral
# board/run-out description are NOT leakage and must not match (false-positive guard,
# verified on the 5066-hand corpus where "villain showed" was range evidence ×11).
_RESULT_LEAK = (
    'because hero won', 'because hero lost', 'because it won', 'because it lost',
    'since the river bricked', 'as it turned out', 'in hindsight',
    'correct because hero won', 'wrong because hero lost', 'hero rivered',
    'justified because it held', 'because the hand held up',
)


def is_blank(text):
    return not (text or '').strip()


def classify_register(*, verdict_class, gradeable=True, result_only=False):
    """§9 register. verdict_class is a coarse class:
      'mistake' / 'borderline' / 'exploit' / 'leak' / 'discipline' -> coaching
      'correct' / 'standard' / 'neutral'                            -> factual
    A result-only or non-gradeable spot is ALWAYS no_clear_lesson (hard rule §9)."""
    if result_only or not gradeable:
        return 'no_clear_lesson'
    vc = (verdict_class or '').strip().lower()
    if vc in ('mistake', 'borderline', 'exploit', 'leak', 'discipline',
              'review', 'too wide', 'missed', 'punt'):
        return 'coaching'
    if vc in ('correct', 'standard', 'neutral', 'good', 'justified', 'baseline'):
        return 'factual'
    # unknown gradeability -> safest non-scoring register
    return 'no_clear_lesson'


def evidence_tier_ok(tier, text):
    """§10 / L8: exact verbs are allowed ONLY on chart_sourced. Returns True when the
    wording is consistent with the tier (no over-claim)."""
    t = (text or '').lower()
    if tier == 'chart_sourced':
        return True
    if tier == 'result_only':
        return True  # result-only never carries a scored verb anyway (gated elsewhere)
    return not any(v in t for v in _EXACT_VERBS)


# v8.19.0 Chapter F (COM-002): typed insufficient-evidence reasons. An INSUFFICIENT_EVIDENCE
# capsule must say WHY the evidence is insufficient, not a generic "evidence is thin".
INSUFFICIENT_REASONS = ('result_only', 'non_gradeable_spot', 'unprovable_node_type',
                        'insufficient_evidence_for_grade', 'evidence_threshold_not_met')
_INSUFFICIENT_REASON_COPY = {
    'result_only': 'result-derived only — the outcome is known but the decision is not gradeable '
                   'from decision-time information',
    'non_gradeable_spot': 'not a gradeable spot — no legal decision to score here',
    'unprovable_node_type': 'unprovable node type — no chart / price authority applies at this decision',
    'insufficient_evidence_for_grade': 'evidence present but below the bar to grade — check the price '
                                       'and the opponent range before scoring',
    'evidence_threshold_not_met': 'no decision-time evidence anchor (price / range / exploit) was '
                                  'available to grade this spot',
}


def build_capsule(street, roles, *, register, evidence_tier, reason=None):
    """Assemble the smallest useful prioritized capsule. `roles` is a dict keyed by
    CAPSULE_ROLES; blank/missing roles are dropped (no empty capsules, §2). Returns
    {street, register, evidence_tier, roles, order, has_anchor, md, insufficient_reason}
    or None when there is no non-blank role to show. A scored register (factual/coaching)
    keeps a visible evidence anchor among Math/Range/Exploit; an INSUFFICIENT_EVIDENCE
    capsule carries a TYPED reason (COM-002) stating exactly what is missing."""
    roles = roles or {}
    present = [(r, str(roles[r]).strip()) for r in CAPSULE_ROLES
               if r in roles and not is_blank(roles.get(r))]
    if not present:
        return None
    anchor_roles = ('Math', 'Range', 'Exploit')
    has_anchor = any(r in anchor_roles for r, _ in present)
    parts = ['**%s:** %s' % (r, v) for r, v in present]
    md = ' · '.join(parts)
    return {
        'street': street,
        'register': register,
        'evidence_tier': evidence_tier,
        'roles': [r for r, _ in present],
        'order': [r for r in CAPSULE_ROLES if r in dict(present)],
        'has_anchor': has_anchor,
        'insufficient_reason': reason if register == 'no_clear_lesson' else None,
        'md': md,
    }


# v8.18.0 final correction: the VISIBLE register badge now uses the canonical contract vocabulary
# (FACTUAL/COACHING/INSUFFICIENT_EVIDENCE) with concise user-facing labels -- never the old generic
# "Unclear"/"Read". INSUFFICIENT_EVIDENCE must be accompanied by the specific limitation in the body.
_REGISTER_BADGE = {
    'factual': 'Fact', 'coaching': 'Coach', 'no_clear_lesson': 'Insufficient evidence',
}

# verdict words that mean a scored coaching spot vs a neutral/correct factual one.
_COACH_VERDICT = ('mistake', 'over-jam', 'overjam', 'too wide', 'too loose', 'punt',
                  'spew', 'leak', 'missed', 'thin', 'loose', 'bluff-catch', 'review',
                  'compounded', 'over-fold', 'overfold')
_FACTUAL_VERDICT = ('standard', 'correct', 'fine', 'good', 'justified', 'value',
                    'snap', 'clear call', 'clear fold', 'baseline')


def decision_capsule_from_signals(street, *, decision_label='', verdict_hint='',
                                  analyst_why='', required_eq_pct=None,
                                  multiway_suppressed=False, range_line='',
                                  exploit_line='', caveat_line='', consequence_line='',
                                  pko_how_changes='', evidence_tier='chart_sourced',
                                  result_only=False, gradeable=True):
    """v8.17 §9 — build the smallest useful DECISION capsule for a street from the
    canonical signals already computed by the renderer (no recompute, invents nothing).
    Picks the register from the verdict wording, fills only non-blank roles, keeps a
    visible evidence anchor (Math/Range/Exploit). Returns a build_capsule() dict or
    None. The PKO how-changes line is folded into Why (it IS the decision driver)."""
    vh = (verdict_hint or '').strip()
    why = (analyst_why or '').strip() or vh
    vc = (vh + ' ' + why).lower()
    # a result-derived hint ("…vs shown", "realized", "rivered") must NEVER become a
    # graded coaching verdict (§9 hard rule / L6 / L13): drop it as the Verdict and
    # let the range/price evidence carry a FACTUAL capsule instead.
    vh_is_result = any(w in vc for w in ('vs shown', 'shown', 'realized', 'rivered',
                                         'at showdown'))
    if not vh_is_result and any(k in vc for k in _COACH_VERDICT) or ('-ev' in vc and not vh_is_result):
        verdict_class = 'mistake'
    elif any(k in vc for k in _FACTUAL_VERDICT) or '+ev' in vc:
        verdict_class = 'correct'
    else:
        verdict_class = ''
    # COR-002 (v8.18.1) fail-safe: in an UNSUPPORTED multiway / covering re-jam spot the price-based
    # "+EV vs range" verdict was derived from a single villain's range (e.g. the short CO jam) and
    # ignores the covering re-jam, so it must NEVER assert a coaching-correct verdict. Drop the
    # price-derived classification; the capsule becomes a neutral FACTUAL/insufficient note instead of
    # contradicting the canonical decision status.
    if multiway_suppressed:
        verdict_class = ''
    register = classify_register(verdict_class=verdict_class, gradeable=gradeable,
                                 result_only=result_only)
    roles = {}
    if decision_label:
        roles['Decision'] = decision_label
    # COR-002: suppress the price-based "+EV vs range" verdict when the multiway composition is
    # unsupported -- it is not a reliable verdict and would contradict the canonical decision status.
    if vh and not vh_is_result and not multiway_suppressed:
        roles['Verdict'] = vh
    # Why: prefer the PKO how-changes driver, else the analyst why (never a result hint).
    drv = (pko_how_changes or '').replace('How the bounty changes it: ', '').strip()
    if drv:
        roles['Why'] = drv
    elif analyst_why and analyst_why != vh:
        roles['Why'] = analyst_why
    if required_eq_pct not in (None, '', 0, '0') and not multiway_suppressed:
        roles['Math'] = 'need %s%% to continue' % required_eq_pct
    if range_line:
        roles['Range'] = range_line
    if exploit_line:
        roles['Exploit'] = exploit_line
    if caveat_line or multiway_suppressed:
        roles['Caveat'] = caveat_line or ('multiway / covering re-jam — the single-villain price is not '
                                          'authoritative here; compare equity to the field, not one jam')
    if consequence_line:
        roles['Consequence'] = consequence_line
    # Anchor-aware fallback: an ungraded but evidenced decision (decision + price/range
    # anchor) is a FACTUAL capsule (neutral facts, no verdict) — NOT "can't infer".
    # no_clear_lesson is reserved for the genuinely un-evidenced / un-gradeable spot.
    _has_anchor = any(r in roles for r in ('Math', 'Range', 'Exploit'))
    _unprovable = ('unavailable' in (decision_label + ' ' + vh).lower()
                   or 'unprovable' in vc or 'node type' in vc)
    # addendum B (FACTS_AVAILABLE_BUT_ACTION_UNGRADEABLE) / E (Range Lens): a PROVEN factual anchor
    # (canonical range membership / price) is FACTUAL evidence, so it must NOT sit under an
    # "Insufficient evidence" headline that implies nothing is known -- even when the ACTION verdict
    # itself cannot be graded. Promote to factual on a proven anchor; when the verdict is ungradeable,
    # keep a PRECISE caveat that names what the unresolved part is (not a generic "below the bar").
    _proven_fact = _has_anchor and not result_only and not _unprovable
    if register == 'no_clear_lesson' and _proven_fact:
        register = 'factual'
        if not gradeable:
            roles.setdefault('Caveat', 'the evidence above is a canonical fact; the action verdict itself '
                             'is not graded here without a decision-time price and opponent-range read')
    # no_clear_lesson must not carry a scored verdict (hard rule §9)
    _reason = None
    if register == 'no_clear_lesson':
        roles.pop('Verdict', None)
        # COM-002 (v8.19.0): attach a TYPED reason WHY evidence is insufficient and use it as
        # the visible Caveat instead of a generic "evidence is thin".
        if result_only:
            _reason = 'result_only'
        elif not gradeable:
            _reason = 'non_gradeable_spot'
        elif _unprovable:
            _reason = 'unprovable_node_type'
        elif _has_anchor:
            _reason = 'insufficient_evidence_for_grade'
        else:
            _reason = 'evidence_threshold_not_met'
        # keep a more-specific existing caveat (e.g. the multiway COR-002 note); else show the typed one.
        roles.setdefault('Caveat', _INSUFFICIENT_REASON_COPY[_reason])
    return build_capsule(street, roles, register=register, evidence_tier=evidence_tier,
                         reason=_reason)


def render_capsule_md(capsule):
    """Render a §9 capsule to a compact, visually-distinct markdown block for the
    Commentary cell: a register badge + the prioritized role lines (Consequence is
    visually subordinate). Returns '' for an empty capsule. The caller wraps this in a
    `.analyst-notes pb-capsule pb-cap-<register>` div so the router places it and the
    CSS styles it distinctly. Never echoes a role twice."""
    if not capsule:
        return ''
    reg = capsule['register']
    badge = _REGISTER_BADGE.get(reg, '')
    # rebuild from order so Consequence renders last + subordinate
    return '🧭 **%s** · %s' % (badge, capsule['md'])


def capsule_content_lints(text, *, register=None, evidence_tier=None,
                          has_anchor=None, range_outside=False,
                          verdict_approves=False, has_takeaway=None):
    """§14 content lints on ONE rendered capsule's visible text. Returns a list of
    (lint_id, severity, message). FAIL severities gate the build; WARN are advisory.
    PURE; every input is an already-derived signal (no recompute)."""
    out = []
    t = (text or '')
    tl = t.lower()
    # L9 missing register / evidence tier
    if register not in REGISTERS:
        out.append(('L9', 'FAIL', 'capsule missing a valid register'))
    if evidence_tier not in EVIDENCE_TIERS:
        out.append(('L9', 'FAIL', 'capsule missing a valid evidence tier'))
    # L1 verdict/range contradiction (approval while the range is outside)
    if verdict_approves and range_outside:
        out.append(('L1', 'FAIL', 'verdict approves while the range is outside without override'))
    # L2 banned generic filler
    for g in BANNED_GENERIC:
        if g in tl:
            out.append(('L2', 'FAIL', 'banned generic filler: "%s"' % g))
            break
    # L3 internal-token leakage
    for tok in INTERNAL_TOKENS:
        if tok in tl:
            out.append(('L3', 'FAIL', 'internal/debug token visible: "%s"' % tok))
            break
    # L6 terminal-result leakage used as decision proof
    for r in _RESULT_LEAK:
        if r in tl:
            out.append(('L6', 'FAIL', 'terminal-result leakage used as decision proof: "%s"' % r))
            break
    # L13 result-only scored
    if evidence_tier == 'result_only' and register in ('factual', 'coaching'):
        out.append(('L13', 'FAIL', 'result-only evidence used with a scored register'))
    # L7 factual capsule carries praise / a lesson
    if register == 'factual' and (has_takeaway or any(
            p in tl for p in ('next time', 'should have', 'take away', 'remember to',
                              'great ', 'nice ', 'well played'))):
        out.append(('L7', 'FAIL', 'factual capsule contains praise or a takeaway'))
    # L9b no_clear_lesson must not carry a scored verdict
    if register == 'no_clear_lesson' and verdict_approves:
        out.append(('L9', 'FAIL', 'no_clear_lesson capsule carries a scored verdict'))
    # L12 scored capsule missing a visible evidence anchor
    if register in ('factual', 'coaching') and has_anchor is False:
        out.append(('L12', 'FAIL', 'scored capsule lacks a visible evidence anchor'))
    # coaching capsule should carry exactly one takeaway (advisory)
    if register == 'coaching' and has_takeaway is False:
        out.append(('L7c', 'WARN', 'coaching capsule has no clear takeaway'))
    # L8 evidence-tier / verb mismatch (over-claim)
    if evidence_tier in EVIDENCE_TIERS and not evidence_tier_ok(evidence_tier, t):
        out.append(('L8', 'WARN', 'wording asserts chart-exactness above the evidence tier'))
    return out


def scan_visible_text_lints(text):
    """Run only the TEXT-derivable content lints (L2 banned generic / L3 internal
    token / L6 terminal-result leakage) over already-tag-stripped VISIBLE commentary
    text. Used by the live migration audit to validate real-report capsule copy without
    per-capsule structured signals. Returns {l2,l3,l6, hits:[(lint,phrase)]}."""
    tl = (text or '').lower()
    hits = []
    for g in BANNED_GENERIC:
        if g in tl:
            hits.append(('L2', g))
    for tok in INTERNAL_TOKENS:
        if tok in tl:
            hits.append(('L3', tok))
    for r in _RESULT_LEAK:
        if r in tl:
            hits.append(('L6', r))
    return {'l2': sum(1 for h in hits if h[0] == 'L2'),
            'l3': sum(1 for h in hits if h[0] == 'L3'),
            'l6': sum(1 for h in hits if h[0] == 'L6'),
            'hits': hits}


def capsule_lint_summary(lint_lists):
    """Aggregate per-capsule lint lists into counts + a FAIL flag for the build gate."""
    fails, warns = 0, 0
    by_id = {}
    for ll in (lint_lists or []):
        for lid, sev, _ in (ll or []):
            by_id[lid] = by_id.get(lid, 0) + 1
            if sev == 'FAIL':
                fails += 1
            else:
                warns += 1
    return {'fail': fails, 'warn': warns, 'by_id': by_id, 'gate_ok': fails == 0}
