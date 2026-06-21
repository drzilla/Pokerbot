"""v8.13.0 — Villain Exploitation Teaching Layer (builder).

A render-facing PROJECTION of the already-stamped villain intelligence
(``build_villain_intel()`` output: exploit_opportunities, evidence_atoms,
read_states + the canonical coaching maps). It produces one constrained
"teaching object" per villain exploit / evidence note so the report can answer,
for every note:

    villain_did      — the specific observed action
    cue              — what that action suggests
    archetype        — read label + confidence + evidence_count
    exploit_now      — what Hero should do in THIS decision
    future_exploit   — how to adjust against this villain/profile later
    do_not_overadjust— where the read stops being reliable

HARD CONSTRAINTS (do not relax — see GPT review history):
  * This module INVENTS NOTHING. Every villain-fact field is copied verbatim
    from an existing stamped field; when a source field is missing the field is
    omitted (None) and the renderer prints the single fixed fallback line.
  * No new detector / dimension scoring / archetype taxonomy. We read the maps
    in gem_villain_intel; we never recompute reads.
  * No-hindsight is STRUCTURAL: showdown-leaked atoms (available_before is None)
    can never become a same-hand decision cue — see _no_hindsight().
  * ``do_not_overadjust`` is DERIVED guardrail copy keyed off confidence; it is
    never a claim about the specific villain.
  * PKO cover wording reuses the existing coverage_label string; no bounty
    BB/$ is ever synthesised here.
  * Online vs live: population is a copy suffix + a field only; it changes no
    threshold and never cross-applies a live read into an online report.

v8.14.0 (Slice D — Villain Exploitation v2): the same projection now also
answers the compact per-hand teaching contract (What villain did / Cue / Read /
Confidence / Exploit now / Exploit future / Do not over-adjust / Tag suggestion)
and maps the derived read to a CANDIDATE Natural8 client tag (label + colour).
The tag is a pure projection of the existing read + confidence + no-hindsight
state — weak evidence yields the explicit "Unsure / Tag-me-later" (yellow) tag
rather than a forced colour, and the "Candidate" qualifier is dropped only at
high confidence. No new detector, scoring, or taxonomy is introduced here.
"""

import re

# Single fixed fallback line for thin / hindsight-gated reads (slice spec).
FALLBACK_LINE = ("Read is weak — one cue only. Use as a review candidate, "
                 "not an exploit mandate.")

# Derived, confidence-keyed guardrail copy. NEVER a villain-specific fact.
# rev-2: the low-confidence default is GENERIC (the old copy assumed a PKO /
# preflop-compression spot, which is wrong for river stations, donks, min-bets
# and pivots). Context-specific low-confidence lines are used ONLY when the read
# family is safely mapped; everything else gets the generic line.
_DO_NOT_OVERADJUST_GENERIC = {
    'low': "Thin read — confirm with more evidence before making a large exploit.",
    'medium': "One read source — confirm it before committing to it again.",
    'high': "Strong sample, but stay balanced; villains adapt once exploited.",
}
_LOW_CONF_CONTEXT = {
    'pko': ("Thin read — cold-calls behind can re-compress the range; small "
            "pairs are not automatic calls."),
    'Sticky Passive': "Thin read — do not assume he calls overbets from one showdown.",
    'Nit / Rock': "Thin read — do not steal any two until the overfold sample repeats.",
    'Aggressive': ("Thin read — respect the first big pivot, but do not label him "
                   "a maniac from one hand."),
}


def derive_do_not_overadjust(confidence, read_label='', has_pko=False):
    """Guardrail copy keyed by confidence. For LOW confidence, use a context-
    specific caution ONLY when the read family is safely mapped (PKO/cold-call,
    station, nit, aggressive); otherwise the generic line. Never a villain fact."""
    if confidence == 'low':
        if has_pko:
            return _LOW_CONF_CONTEXT['pko']
        rl = read_label or ''
        for key in ('Sticky Passive', 'Nit / Rock', 'Aggressive'):
            if key in rl:
                return _LOW_CONF_CONTEXT[key]
        return _DO_NOT_OVERADJUST_GENERIC['low']
    return _DO_NOT_OVERADJUST_GENERIC.get(confidence, _DO_NOT_OVERADJUST_GENERIC['low'])


# ── Status safety: trusted baseline + grade buckets (Step 2 / Option B) ─────
# A villain teaching object may only present a graded missed/good EXPLOIT when a
# TRUSTED BASELINE backs it. For this slice the trusted families are the
# preflop-chart-backed steal/nit detectors (which already gate on Hero's open
# chart + read confidence). Every other detector — postflop value, multiway
# donks, weird sizing, station call-downs, generic LAG/maniac pressure — has NO
# trusted baseline, so its read teaches as candidate/future/evidence, never a
# graded missed/good. Broad postflop/multiway grading stays disabled here.
_TRUSTED_BASELINE_DETECTORS = {
    'missed_steal_vs_nit', 'missed_steal_vs_nit_blinds', 'good_steal_vs_nit',
}
# Variance-increasing exploit families. ICM is a COARSE CAUTION only — the
# pipeline carries no payout ladder / risk-premium / per-hand ICM pressure at
# teaching-build time (see audit), so we never quantify ICM; for risky-widening
# advice we attach a neutral pay-jump caution and an icm_pressure_unknown
# source-warning rather than a graded suppression.
_RISKY_EXPLOIT_DETECTORS = {
    'ego_fought_maniac', 'overfolded_vs_aggro', 'opened_too_loose_vs_aggro',
    'missed_steal_vs_nit', 'missed_steal_vs_nit_blinds', 'good_steal_vs_nit',
    'missed_thin_value_vs_sticky',
}
# Only WIDENING / variance-INCREASING phrases (a generic 'bluff' would wrongly
# flag "do not bluff"; "value-bet thinner" is low-variance value). These mean
# Hero is being told to do MORE: steal/iso wider, call down lighter, stack off
# lighter, bluff more, ego-raise, thin value INTO jam risk.
_RISKY_SO_WHAT_KEYS = ('wider', 'widen', 'call down', 'call-down', 'stack off',
                       'ego-raise', 'ego ', 'bluff more', 'thin value into')
_ICM_CAUTION = ("Under pay-jump / ICM pressure prefer the lower-variance line "
                "unless an exact chart or price confirms the aggressive adjustment.")

# Safe teaching-status buckets. missed/good are GRADED outcomes (trusted-baseline
# only); the rest are teaching notes (never a graded Hero mistake).
_GRADED_STATUSES = {'missed_exploit', 'good_exploit'}


def _baseline_source(detector):
    """'chart_preflop' for a trusted-baseline detector, else 'none'."""
    return 'chart_preflop' if (detector or '') in _TRUSTED_BASELINE_DETECTORS else 'none'


def _is_risky_exploit(detector, so_what):
    """True if the exploit advice is variance-increasing (widen / call-down /
    bluff / ego / thin-value) and therefore wants an ICM caution."""
    if (detector or '') in _RISKY_EXPLOIT_DETECTORS:
        return True
    sw = (so_what or '').lower()
    return any(k in sw for k in _RISKY_SO_WHAT_KEYS)


def _norm_label(s):
    """Lowercase, strip emoji/punct/'candidate'/population-suffix for comparison."""
    s = re.sub(r'\([^)]*\)\s*$', '', str(s or ''))          # trailing (suffix)
    s = re.sub(r'[^a-z ]', ' ', s.lower())
    s = s.replace('candidate', ' ')
    return ' '.join(s.split())


def _cue_is_explanatory(cue, archetype):
    """True iff the cue EXPLAINS the behaviour (range/frequency/tendency) rather
    than merely restating the read label. A cue that normalises to the archetype
    label (or is too short to add information) is non-explanatory and is dropped
    so the card never shows 'Cue: Sticky Passive' next to 'Read: Sticky Passive'."""
    if not cue:
        return False
    nc, na = _norm_label(cue), _norm_label(archetype)
    if not nc:
        return False
    if nc == na:                       # cue is just the label
        return False
    if na and na in nc and len(nc.split()) <= len(na.split()) + 1:
        return False                   # label plus at most one word — not an explanation
    return True


def _grade_bucket(kind, fallback, baseline_source, confidence, no_hindsight,
                  detector_outcome):
    """Safe teaching-status bucket. A graded missed/good survives ONLY when a
    trusted baseline backs it AND confidence is medium/high AND the read was
    known before the decision; otherwise the read teaches as
    candidate/standard/evidence/watch — never a graded Hero mistake."""
    if fallback:
        return 'watch_only'
    if kind == 'evidence':
        return 'evidence_only'
    graded = detector_outcome in ('missed', 'missed_exploit', 'good', 'good_exploit')
    is_good = detector_outcome in ('good', 'good_exploit')
    if (baseline_source != 'none' and graded and no_hindsight
            and confidence in ('medium', 'high')):
        return 'good_exploit' if is_good else 'missed_exploit'
    # read supports the line but no trusted baseline / not confident enough:
    if detector_outcome in ('standard', 'read_supported_standard'):
        return 'standard_read_supported'
    return 'candidate_read_supported'


# ── Mixed/split profile coherence (Step-2 stabilization) ────────────────────
# A teaching card is incoherent when THIS hand's cue and the villain's read sit
# on different broad behavioural AXES — e.g. a loose-passive open-limp cue next
# to an aggregate "Aggressive" read. We classify the cue's axis (from its signal
# / detector) and the read's axis (from the archetype), and when they cross we
# render an explicit node-specific "Mixed profile" caveat BEFORE the archetype
# rather than a clean global tag. Same-axis pairs (loose-passive + sticky) stay
# coherent. Passive-to-aggression is a LINE-SPECIFIC pivot, not a contradiction.
# Derived here from already-available fields; an upstream profile_label, if a
# future source provides one, wins.
_AXIS_BY_SIGNAL = {
    'open_limp': 'passive', 'limp_call': 'passive', 'multiway_donk': 'passive',
    'weird_minbet': 'passive', 'cold_call_3bet_oop': 'passive',
    'weak_showdown_call': 'passive', 'calldown_weak_pair': 'passive',
    'repeated_blind_overfold': 'tight',
    'passive_aggro_pivot': 'pivot', 'river_bluff_shown': 'aggro',
}
_AXIS_BY_DETECTOR = {
    'bluffed_sticky': 'passive', 'missed_thin_value_vs_sticky': 'passive',
    'paid_off_passive_aggression': 'passive', 'good_fold_vs_passive_aggro': 'passive',
    'missed_steal_vs_nit_blinds': 'tight', 'missed_steal_vs_nit': 'tight',
    'good_steal_vs_nit': 'tight',
    'opened_too_loose_vs_aggro': 'aggro', 'overfolded_vs_aggro': 'aggro',
    'ego_fought_maniac': 'aggro', 'pivot_overplayed': 'pivot',
}
_CUE_NODE_BY_SIGNAL = {
    'open_limp': 'preflop entry', 'limp_call': 'preflop entry',
    'cold_call_3bet_oop': 'preflop flat', 'repeated_blind_overfold': 'blind defense',
    'multiway_donk': 'postflop lead', 'weird_minbet': 'postflop sizing',
    'weak_showdown_call': 'showdown call', 'calldown_weak_pair': 'multi-street call',
    'passive_aggro_pivot': 'turn/river', 'river_bluff_shown': 'river',
}
_AXIS_DESC = {'passive': 'loose-passive / calling', 'aggro': 'pressure-heavy',
              'tight': 'tight / folding'}


def _read_axis(archetype):
    """Broad behavioural axis of a read label: passive / aggro / tight (or None
    for solid/unknown, where no split is asserted)."""
    fam = _archetype_family(archetype)
    if fam in ('aggro', 'danger'):
        return 'aggro'
    if fam in ('station', 'fish', 'whale', 'funrec'):
        return 'passive'
    if fam == 'nit':
        return 'tight'
    return None


def derive_profile(cue_axis, cue_node, archetype, explicit=None, read_conf='low'):
    """Return (profile_label, profile_caveat) for the Read line.

    A cross-axis cue (this hand's cue on a different behavioural axis than the
    villain's AGGREGATE read) is a NODE-SPECIFIC observation, not a contradiction
    of the read. The caveat is therefore COMPACT and confidence-calibrated, so it
    teaches without over-warning on the ~55% of hands where a single cue differs
    from the multi-hand read:
      * confident aggregate read (medium/high) -> the read STANDS; this hand's cue
        is just local: "Node-specific … cue — the read is from other spots".
      * forming read (low) -> softer: "Node-specific … cue — read still forming".
      * passive->aggression -> a line-specific pivot value warning.
    It never says "contradiction"/"Mixed profile" for a confident read (which was
    misleading — the profile is not mixed, the cue is node-local). A future
    upstream profile_label, if provided, wins and uses the explicit label. The
    caveat is None when coherent (same axis)."""
    if explicit in ('mixed', 'split'):
        return explicit, '%s profile' % explicit.capitalize()
    if explicit == 'consistent':
        return 'consistent', None
    if cue_axis == 'pivot':
        return 'split', 'Line-specific pivot — value warning for this line, not a global read'
    rax = _read_axis(archetype)
    if cue_axis in ('passive', 'aggro', 'tight') and rax and cue_axis != rax:
        node = (cue_node + ' ') if cue_node else ''
        tail = ('the read is from other spots' if read_conf in ('medium', 'high')
                else 'read still forming')
        return 'split', ('Node-specific %scue — %s' % (node, tail))
    return 'consistent', None


def _aggregate_profile_override(read_state):
    """The AGGREGATE profile_label (from gem_villain_intel._build_read_states)
    that should OVERRIDE the per-hand cue/read derivation. A genuine multi-axis
    aggregate ('split'/'mixed') dominates and stamps a profile caveat; a
    'consistent' aggregate (or none) returns None so this hand's node-specific
    cue can still be flagged by derive_profile's per-hand branch."""
    pl = (read_state or {}).get('profile_label')
    return pl if pl in ('split', 'mixed') else None


# ── Natural8 client tag taxonomy (Slice D) ──────────────────────────────────
# Ron's Natural8 colour-tag scheme. We map a DERIVED read family -> a candidate
# client tag. This is a projection, not a new classifier: the read itself comes
# from gem_villain_intel; here we only translate it into the tag Ron would apply
# in his client, and only when the evidence is strong enough to suggest one.
_N8_TAG_UNSURE = ('Unsure / Tag-me-later', 'yellow')
_N8_TAGS = {
    'danger':  ('Danger Reg', 'red'),
    'solid':   ('Solid Reg', 'purple'),
    'nit':     ('Nit/Rock', 'brown'),
    'station': ('Calling Station', 'orange'),
    'aggro':   ('Maniac/LAG', 'pink'),
    'fish':    ('Fish', 'blue'),
    'whale':   ('Whale', 'cyan'),
    'funrec':  ('Fun Rec / Gambler', 'lime'),
}


def _archetype_family(archetype):
    """Map a read/archetype label to a tag-family key (or None when unmapped).

    Tolerant of emoji prefixes and the 'Candidate ' qualifier; matches the
    canonical read phrases. 'Unknown'/missing -> None (no forced tag)."""
    a = (archetype or '').lower()
    if not a or 'unknown' in a:
        return None
    if 'danger' in a:
        return 'danger'
    if 'maniac' in a or re.search(r'\blag\b', a) or 'aggressive' in a or 'aggro' in a:
        return 'aggro'
    if 'nit' in a or 'rock' in a:
        return 'nit'
    if 'station' in a or 'sticky' in a or 'loose passive' in a or 'calling' in a:
        return 'station'
    if 'solid' in a:
        return 'solid'
    if 'whale' in a:
        return 'whale'
    if 'fish' in a:
        return 'fish'
    if 'fun rec' in a or 'gambler' in a or 'recreation' in a:
        return 'funrec'
    return None


def suggest_natural8_tag(archetype, confidence, evidence_count, no_hindsight):
    """Suggest a CANDIDATE Natural8 client tag {label, color, kind} for a read.

    Pure projection — invents no read. Weak evidence (low confidence, a single
    cue, hindsight-gated, or an unmapped archetype) returns the explicit
    'Unsure / Tag-me-later' (yellow) tag rather than forcing a colour. The
    'Candidate ' qualifier is dropped only at high confidence. High-confidence
    aggression escalates Maniac/LAG -> Danger Reg (the tournament threat tag)."""
    n = int(evidence_count or 0)
    fam = _archetype_family(archetype)
    if confidence == 'low' or n <= 1 or not no_hindsight or fam is None:
        return {'label': _N8_TAG_UNSURE[0], 'color': _N8_TAG_UNSURE[1], 'kind': 'unsure'}
    # A well-corroborated aggressive read is a 'Danger Reg', not just a Maniac.
    if fam == 'aggro' and confidence == 'high':
        fam = 'danger'
    label, color = _N8_TAGS[fam]
    if confidence != 'high':
        label = 'Candidate ' + label
    return {'label': label, 'color': color, 'kind': fam}


def _candidate_archetype(archetype, confidence):
    """Read label for display: 'Candidate <X>' unless high confidence; an
    unknown/missing read becomes the explicit 'Unknown / Tag-me-later'."""
    a = (archetype or '').strip()
    if not a or a.lower() == 'unknown':
        return 'Unknown / Tag-me-later'
    if confidence == 'high':
        return a
    return 'Candidate ' + a


# Canonical exploit read-label -> the atom dimensions that CORROBORATE it.
# Used only to count same-decision-type evidence for confidence (no new scoring).
_READ_FAMILY_DIMS = {
    'Sticky Passive': {'sticky'},
    'Loose Passive': {'loose_passive'},
    'Nit / Rock': {'tight'},
    'Aggressive': {'aggressive', 'pivot'},
}

# v8.18.1: future_exploit is NO LONGER word-capped -- the canonical sentence must stay complete (the
# renderer shortens for display only). Caps remain for the short observation/cue/exploit-now lines.
_WORD_CAP = {'villain_did': 22, 'exploit_now': 18, 'cue': 24}


def _clamp_words(text, limit):
    """Hard word-cap (mirrors gem_coaching_cards._clamp_words)."""
    if not text:
        return text
    w = str(text).split()
    return ' '.join(w[:limit]) if len(w) > limit else str(text)


def _clean(text):
    return (str(text).strip() or None) if text else None


def derive_confidence(read_source, evidence_count, same_type):
    """Confidence from REAL evidence only (slice §confidence rules).

    * population tendency with no direct evidence -> always 'low'
    * strong corroborated sample -> 'high'
    * one direct cue + supporting profile -> 'medium'
    * one cue / conflicting / stale -> 'low'
    A low-confidence read can never be promoted; callers must not let it force a
    high-confidence mistake verdict (the renderer shows it as a review note).
    """
    if read_source == 'profiler_archetype':
        return 'low'
    n = int(evidence_count or 0)
    st = int(same_type or 0)
    if n >= 8 and st >= 2:
        return 'high'
    if n >= 4 and st >= 1:
        return 'medium'
    return 'low'


def _no_hindsight(read_source, available_before, hero_decision_index):
    """STRUCTURAL no-hindsight guard. Returns True iff the cue was known to Hero
    BEFORE the decision (prior-hand / population / same-hand-but-earlier-action).

    Showdown-leaked atoms set available_before_action_index = None in
    gem_villain_intel; they therefore can never satisfy the same-hand branch and
    can never become an actionable same-hand cue.
    """
    if read_source in ('prior_atoms_mapped', 'profiler_archetype'):
        return True  # built from earlier hands / population — not this showdown
    if read_source == 'same_hand_pivot':
        return (available_before is not None
                and hero_decision_index is not None
                and available_before <= hero_decision_index)
    # evidence-note atom: actionable only if available before an action index
    return available_before is not None


def _same_type_count(atoms_by_villain, villain_key, read_label):
    """Count corroborating atoms (same read family). Drives confidence."""
    fams = _READ_FAMILY_DIMS.get(read_label, set())
    if not fams:
        return 0
    return sum(1 for a in (atoms_by_villain.get(villain_key) or [])
               if a.get('dimension') in fams)


def _population_suffix(population):
    return (' (live read — do not cross-apply to online)' if population == 'live'
            else ' (online-pool read)')


def _pko_subobject(pko_by_hand, hand_id):
    """Optional cover-status sub-object — reuses the existing coverage_label
    string verbatim. NEVER synthesises a bounty BB/$ figure. Omitted when no
    clean PKO context exists for the hand."""
    ctx = (pko_by_hand or {}).get(hand_id) or {}
    label = ctx.get('coverage_label')
    if not label:
        return None
    out = {'cover_label': label}
    if 'can_collect_bounty' in ctx:
        out['collectible'] = bool(ctx.get('can_collect_bounty'))
    elif 'coverage_bucket' in ctx:
        out['collectible'] = (ctx.get('coverage_bucket') == 'Hero covers')
    return out


def _tag_line(obj):
    """The 'Tag suggestion:' line from the object's stamped tag, or None."""
    tag = obj.get('tag_suggestion') or {}
    if tag.get('label'):
        return 'Tag suggestion: %s (%s)' % (tag['label'], tag.get('color') or 'yellow')
    return None


def _teach_lines(obj):
    """Pre-render the FULL compact teaching contract in PYTHON so the renderer
    only displays strings (it cannot invent facts). Slice D order:

        What villain did -> Cue -> Read -> Confidence -> Exploit now ->
        Exploit future -> Do not over-adjust -> Bounty -> Tag suggestion

    For thin / hindsight-gated objects only the fixed fallback line is shown,
    followed by the (always 'Unsure / Tag-me-later') tag line so the report
    still tells Ron what to do in his client: tag later."""
    if obj.get('fallback'):
        lines = [FALLBACK_LINE]
        tl = _tag_line(obj)
        if tl:
            lines.append(tl)
        return lines
    lines = []
    if obj.get('villain_did'):
        lines.append('What villain did: ' + obj['villain_did'])
    if obj.get('cue'):
        lines.append('Cue: ' + obj['cue'])
    # A mixed/split profile caveat renders BEFORE the broad archetype label so
    # the read is never presented as a single clean type when it is not. The
    # node-specific caveat (when derived) explains the cross-axis split.
    _read = _candidate_archetype(obj.get('archetype'), obj.get('confidence'))
    _cav = obj.get('profile_caveat')
    _prof = (obj.get('profile_label') or '').lower()
    if _cav:
        _read = _cav + ' — ' + _read
    elif _prof in ('mixed', 'split'):
        _read = _prof.capitalize() + ' profile — ' + _read
    lines.append('Read: ' + _read)
    if obj.get('confidence'):
        conf = str(obj['confidence'])
        ec = obj.get('evidence_count')
        if isinstance(ec, int):
            conf += ' · %d cue%s' % (ec, '' if ec == 1 else 's')
        lines.append('Confidence: ' + conf)
    if obj.get('exploit_now'):
        lines.append('Exploit now: ' + obj['exploit_now'])
    if obj.get('future_exploit'):
        lines.append('Exploit future: ' + obj['future_exploit'])
    if obj.get('do_not_overadjust'):
        lines.append('Do not over-adjust: ' + obj['do_not_overadjust'])
    # ICM is a coarse caution (no risk-premium math): risky-widening advice is
    # cautioned, never quantified. Kept as its OWN line so the confidence-keyed
    # do_not_overadjust copy stays exactly the derived guardrail string.
    if obj.get('icm_guardrail'):
        lines.append('ICM caution: ' + obj['icm_guardrail'])
    pko = obj.get('pko')
    if pko and pko.get('cover_label'):
        lines.append('Bounty: ' + pko['cover_label'])
    tl = _tag_line(obj)
    if tl:
        lines.append(tl)
    return lines or [FALLBACK_LINE]


def _finalize(obj):
    """Apply word caps + attach pre-rendered teach_lines; stamp fallback."""
    obj['villain_did'] = _clamp_words(obj.get('villain_did'), _WORD_CAP['villain_did'])
    obj['cue'] = _clamp_words(obj.get('cue'), _WORD_CAP['cue'])
    obj['exploit_now'] = _clamp_words(obj.get('exploit_now'), _WORD_CAP['exploit_now'])
    # Fallback if there is no real villain_did/cue OR nothing actionable to say.
    thin = (not obj.get('villain_did') and not obj.get('cue'))
    if thin:
        obj['fallback'] = True
    # v8.18.1 (Villain Teaching quality hotfix): an ELIGIBLE read carries a CUE-FIRST, COMPLETE future
    # exploit + provenance. Generate one cue-first when the producer left it empty; keep a genuinely
    # pre-authored recommendation (MANUAL_EXISTING) ONLY when it passes the completeness + cue-alignment
    # bar, else regenerate cue-first. The canonical future_exploit is NEVER word-sliced -- any shortening
    # happens in the renderer (display clamp / expandable), so the full sentence stays in the payload and
    # the accessibility layer. Missing future_exploit remains an INCOMPLETE-eligible state, not ineligible.
    if (not obj.get('fallback') and obj.get('cue') and obj.get('archetype') and obj.get('exploit_now')):
        prov = derive_future_exploit(obj)
        pre = _clean(obj.get('future_exploit'))
        if pre and future_exploit_complete(pre)[0] and cue_alignment(prov['cue_family'], pre)[0]:
            obj['future_exploit'] = pre
            obj['future_exploit_source'] = 'MANUAL_EXISTING'
            obj['alignment_reason'] = ('pre-authored exploit recommendation; passes completeness + %s '
                                       'alignment' % prov['cue_family'])
        else:
            obj['future_exploit'] = prov['future_exploit']
            obj['future_exploit_source'] = prov['future_exploit_source']
            obj['alignment_reason'] = prov['alignment_reason']
        obj['cue_family'] = prov['cue_family']
        obj['current_exploit_domain'] = prov['current_exploit_domain']
    # Natural8 candidate tag (Slice D). A fallback / weak read is explicitly
    # 'Unsure / Tag-me-later' — never a forced colour; otherwise project the
    # derived read + confidence + no-hindsight state into a candidate tag.
    if obj.get('fallback'):
        obj['tag_suggestion'] = {'label': _N8_TAG_UNSURE[0],
                                 'color': _N8_TAG_UNSURE[1], 'kind': 'unsure'}
    else:
        nh = bool((obj.get('source_truth') or {}).get('no_hindsight'))
        obj['tag_suggestion'] = suggest_natural8_tag(
            obj.get('archetype'), obj.get('confidence'),
            obj.get('evidence_count'), nh)
    # Safe grade bucket — computed AFTER fallback is finalized. A graded
    # missed/good survives only with a trusted baseline + medium/high confidence
    # + no-hindsight; everything else is candidate/standard/evidence/watch.
    nh2 = bool((obj.get('source_truth') or {}).get('no_hindsight'))
    obj['teaching_status'] = _grade_bucket(
        obj.get('kind', ''), bool(obj.get('fallback')),
        obj.get('baseline_source', 'none'), obj.get('confidence', 'low'),
        nh2, obj.pop('_detector_outcome', ''))
    obj['teach_lines'] = _teach_lines(obj)
    # v8.17 Step-3: the explicit 7-part lesson contract, attached to every
    # object so the Commentary capsule can read it without re-deriving.
    obj['lesson_7part'] = lesson_7part(obj)
    return obj


def lesson_7part(obj):
    """The explicit 7-part Villain Step-3 teaching lesson (spec §Epic3).

    A PURE PROJECTION of an already-built teaching object — invents nothing.
    All seven keys always exist (None when the source field is absent) so the
    capsule/renderer may combine parts concisely while the contract stays whole:

        q1_villain_did    — the specific observed action
        q2_cue            — what that action suggests
        q3_read           — read/archetype (+ split/mixed profile prefix)
        q4_confidence     — confidence tier + cue count
        q5_exploit_now    — what Hero should do in THIS decision (None if hindsight-gated)
        q6_exploit_future — how to adjust against this villain/profile later
        q7_do_not_overadjust — derived guardrail (where the read stops being reliable)

    Plus ``gradable`` (True only when the object reached a graded missed/good)
    and ``non_gradable_reason`` (the factual-moment reason otherwise). A thin /
    hindsight-gated object returns the fixed fallback line in q1 and None
    elsewhere — never a fabricated lesson."""
    if obj.get('fallback'):
        return {
            'q1_villain_did': obj.get('villain_did') or FALLBACK_LINE,
            'q2_cue': None, 'q3_read': None, 'q4_confidence': None,
            'q5_exploit_now': None, 'q6_exploit_future': None,
            'q7_do_not_overadjust': None,
            'gradable': False,
            'non_gradable_reason': obj.get('non_gradable_reason') or 'thin_read',
        }
    # Read line carries the same mixed/split profile prefix _teach_lines uses.
    read = _candidate_archetype(obj.get('archetype'), obj.get('confidence'))
    cav = obj.get('profile_caveat')
    prof = (obj.get('profile_label') or '').lower()
    if cav:
        read = cav + ' — ' + read
    elif prof in ('mixed', 'split'):
        read = prof.capitalize() + ' profile — ' + read
    conf = obj.get('confidence')
    ec = obj.get('evidence_count')
    if conf and isinstance(ec, int):
        conf = '%s · %d cue%s' % (conf, ec, '' if ec == 1 else 's')
    graded = obj.get('teaching_status') in _GRADED_STATUSES
    return {
        'q1_villain_did': obj.get('villain_did'),
        'q2_cue': obj.get('cue'),
        'q3_read': read,
        'q4_confidence': conf,
        'q5_exploit_now': obj.get('exploit_now'),
        'q6_exploit_future': obj.get('future_exploit'),
        'q7_do_not_overadjust': obj.get('do_not_overadjust'),
        'gradable': graded,
        'non_gradable_reason': '' if graded else (obj.get('non_gradable_reason') or ''),
        # v8.18.1 future-exploit provenance (carried into the rendered payload for the quality verifier)
        'cue_family': obj.get('cue_family'),
        'current_exploit_domain': obj.get('current_exploit_domain'),
        'future_exploit_source': obj.get('future_exploit_source'),
        'alignment_reason': obj.get('alignment_reason'),
    }


def teaching_contract(obj):
    """v8.18.0 Villain Teaching: the EXPLICIT data contract for one lesson -- a pure projection over
    the built teaching object, separating OBSERVATION (what was seen) from INFERENCE (what it suggests)
    and exposing the stable identity + the decision sequence position + supporting evidence ids. Alias
    is presentation only, never identity (identity is the stable_villain_key = tournament_id|player_hash)."""
    st = obj.get('source_truth') or {}
    l7 = lesson_7part(obj)
    return {
        'stable_villain_key': obj.get('villain_id'),          # tournament_id|player_hash (identity)
        'villain_alias': obj.get('villain_alias') or '',      # presentation only
        'hand_decision_id': st.get('decision_id'),            # hand_id|street|hero_action_index (sequence)
        'street': obj.get('street'),
        'observation': obj.get('villain_did'),                # what villain DID (observed)
        'inference': obj.get('cue'),                          # what it SUGGESTS (inferred)
        'read_archetype': l7.get('q3_read'),
        'confidence': obj.get('confidence'),
        # current exploit: a concrete adjustment, or NOT_APPLICABLE with a reason when the read was only
        # established AFTER the decision (the action completed before a safe adjustment was possible).
        'current_exploit': (obj.get('exploit_now') if obj.get('exploit_now')
                            else 'NOT_APPLICABLE — the action completed before a safe adjustment was possible'),
        'future_exploit': obj.get('future_exploit'),
        'guardrail': obj.get('do_not_overadjust'),
        'supporting_evidence': list(st.get('evidence_atoms') or []),
        'no_hindsight': st.get('no_hindsight'),
        'gradable': l7.get('gradable'),
    }


# result-oriented phrasings that would mean a showdown/result became an EARLIER confident cue.
_RESULT_ORIENTED_CUES = ('at showdown', 'showed down', 'because hero won', 'because hero lost',
                         'as it turned out', 'in hindsight', 'rivered', 'after the river')


# typed ineligibility reasons (v8.18.0 final): an object is ineligible ONLY for an evidence-based reason.
# Missing future_exploit is NEVER an ineligibility reason -- it is an incomplete-eligible state.
INELIGIBLE_REASONS = ('INSUFFICIENT_EVIDENCE', 'RESULT_ONLY', 'NO_MEANINGFUL_CUE',
                      'NO_SAFE_EXPLOIT_SUPPORTED', 'DUPLICATE_OBJECT')


def villain_teaching_coverage(objects):
    """FULL-POPULATION coverage inventory (v8.18.0 final product-truth correction).

    ELIGIBILITY is decided BEFORE completeness and never from completeness. A lesson is ELIGIBLE when the
    evidence supports an observed villain action + a meaningful cue + a practical read/archetype + a
    non-zero confidence + at least one safe actionable adjustment (a current exploit). An eligible lesson
    stays eligible even if future_exploit is missing -- that is incomplete (missing_fields=['future_
    exploit']), NEVER ineligible. Ineligibility requires a typed evidence reason (INSUFFICIENT_EVIDENCE /
    RESULT_ONLY / NO_MEANINGFUL_CUE / NO_SAFE_EXPLOIT_SUPPORTED / DUPLICATE_OBJECT). Dedup runs FIRST, by
    the canonical lesson identity (stable villain key + hand + decision + cue/evidence).

    Guards (must all be 0): incomplete eligible (after future_exploit generation), duplicate lessons
    remaining, chronology violations, identity collisions, result-oriented violations."""
    raw = duplicates = eligible = complete = incomplete = 0
    ineligible = {r: 0 for r in INELIGIBLE_REASONS}
    chronology_violations = identity_collisions = result_oriented = 0
    seen_lesson = set()
    seen_key_hand = {}
    incomplete_records = []
    sample_complete = []
    for obj in (objects or []):
        raw += 1
        st = obj.get('source_truth') or {}
        did = st.get('decision_id')
        l7 = lesson_7part(obj)
        text = ((obj.get('cue') or '') + ' ' + (obj.get('villain_did') or '')).lower()
        is_result = any(w in text for w in _RESULT_ORIENTED_CUES)
        # whole-population guards
        if st.get('no_hindsight') is False and obj.get('exploit_now'):
            chronology_violations += 1                       # a current exploit from a post-decision read
        if is_result and (obj.get('exploit_now') or obj.get('future_exploit')):
            result_oriented += 1                             # a result/showdown used as an actionable cue
        vk = obj.get('villain_id')
        # identity: the stable key (tournament_id|player_hash) IS the identity, so a collision (one key
        # bound to two different players) is structurally impossible -- reported 0 for completeness.
        # DEDUP FIRST by the canonical lesson identity = stable villain key + decision identity (hand|
        # street|action). A second object for the SAME villain + decision is a duplicate (one decision has
        # one lesson; conflicting cues on the same decision are a duplicate, not two lessons). Duplicates
        # are counted SEPARATELY -- they are removed BEFORE eligibility, not an ineligibility reason.
        lesson_id = (vk, did)
        if did and lesson_id in seen_lesson:
            duplicates += 1
            continue
        if did:
            seen_lesson.add(lesson_id)
        # ELIGIBILITY (decided before completeness): q1 observed action + q2 cue + q3 read + q4 confidence
        # + q5 a safe current exploit. Missing future_exploit (q6) does NOT affect eligibility.
        if obj.get('fallback') or not l7['q1_villain_did'] or not l7['q2_cue']:
            ineligible['INSUFFICIENT_EVIDENCE'] += 1
            continue
        if is_result:
            ineligible['RESULT_ONLY'] += 1
            continue
        if not (l7['q3_read'] and l7['q4_confidence']):
            ineligible['NO_MEANINGFUL_CUE'] += 1
            continue
        if not l7['q5_exploit_now']:
            ineligible['NO_SAFE_EXPLOIT_SUPPORTED'] += 1
            continue
        # ELIGIBLE. COMPLETENESS = q6 future_exploit + q7 guardrail.
        eligible += 1
        missing = []
        if not l7['q6_exploit_future']:
            missing.append('future_exploit')
        if not l7['q7_do_not_overadjust']:
            missing.append('guardrail')
        if not missing:
            complete += 1
            if len(sample_complete) < 5:
                sample_complete.append(did)
        else:
            incomplete += 1
            incomplete_records.append({'decision_id': did, 'missing_fields': missing})
    return {
        'raw_teaching_objects': raw,
        'duplicates_identified': duplicates,
        'unique_objects': raw - duplicates,
        'eligible_lessons': eligible,
        'ineligible_by_reason': ineligible,
        'ineligible_total': sum(ineligible.values()),
        'complete_eligible_lessons': complete,
        'incomplete_eligible_lessons': incomplete,
        'incomplete_records': incomplete_records[:30],
        'duplicate_lessons_remaining': 0,
        'chronology_violations': chronology_violations,
        'identity_collisions': identity_collisions,
        'result_oriented_violations': result_oriented,
        'sample_complete_decision_ids': sample_complete,
    }


# ─────────────────────────────────────────────────────────────────────────────
# v8.18.1 CUE-FIRST future-exploit generation (Villain Teaching quality hotfix)
#
# The future exploit must teach how to exploit the SAME observed cue/line again. Generation order is
# (1) the specific cue family (the structured atom signal is the canonical key; the cue/observation text
# is the fallback), (2) the current exploit / action domain, and (3) the villain archetype ONLY as a
# fallback modifier -- never archetype-first. The canonical sentence is stored COMPLETE (no word slice);
# any shortening is display-only.
# ─────────────────────────────────────────────────────────────────────────────
CUE_FAMILIES = (
    'WIDE_PREFLOP_CALL', 'REPEATED_LIMP', 'EXCESSIVE_FOLD', 'CALLING_STATION', 'WIDE_FLAT_3BET',
    'SMALL_DONK', 'LARGE_DONK', 'PASSIVE_THEN_RAISE', 'OVERSIZED_BET', 'UNDERBLUFFED_RIVER',
    'OVERBLUFFED_AGGR', 'WEAK_STAB', 'EXCESSIVE_3BET', 'FIT_OR_FOLD', 'SHOWDOWN_ONLY', 'GENERIC',
)

# structured atom signal -> cue family (the most reliable, cue-specific mapping)
_SIGNAL_CUE_FAMILY = {
    'open_limp': 'REPEATED_LIMP', 'limp_call': 'WIDE_PREFLOP_CALL', 'multiway_donk': 'LARGE_DONK',
    'weird_minbet': 'SMALL_DONK', 'repeated_blind_overfold': 'EXCESSIVE_FOLD',
    'cold_call_3bet_oop': 'WIDE_FLAT_3BET', 'passive_aggro_pivot': 'PASSIVE_THEN_RAISE',
    'calldown_weak_pair': 'CALLING_STATION', 'weak_showdown_call': 'CALLING_STATION',
    'river_bluff_shown': 'OVERBLUFFED_AGGR',
}

# cue/observation text patterns -> cue family (fallback when no structured signal maps). Ordered:
# the FIRST family whose any-pattern matches wins, so put the more specific lines first.
_CUE_TEXT_FAMILY = (
    ('PASSIVE_THEN_RAISE', ('suddenly aggressive', 'normally passive', 'sudden aggression', 'passive_aggro', 'passive then raise', 'passive line then', 'passive, then raises')),
    ('SMALL_DONK', ('min-bet', 'minimum bet', 'min bet', 'small donk', 'small bet', 'tiny bet')),
    ('LARGE_DONK', ('donk-bet', 'donk bet', 'donks into', 'donk into', 'leads into the field', 'lead into the field', 'oversized donk')),
    ('OVERSIZED_BET', ('oversized', 'overbet', 'over-bet', 'large river bet', 'huge bet', 'big river')),
    ('UNDERBLUFFED_RIVER', ('underbluff', 'under-bluff', 'value-heavy river', 'rarely bluffs', 'never bluffs the river')),
    ('OVERBLUFFED_AGGR', ('over-bluff', 'overbluff', 'bluffs too much', 'over-aggressive', 'maniac', 'spews', 'too many bluffs')),
    ('WIDE_FLAT_3BET', ('flat-call', 'flatting 3-bet', 'flats 3-bet', '3-bet oop', 'cold-call 3', 'calls 3-bets')),
    ('EXCESSIVE_3BET', ('3-bets too', 're-raises too', 'reraises too', 'over-3bet', 'excessive 3-bet', 'light 3-bet')),
    ('EXCESSIVE_FOLD', ('overfold', 'over-fold', 'folds too often', 'folds to steal', 'folds the blind', 'too tight', 'nit', 'nitty', 'rock')),
    ('CALLING_STATION', ('station', 'sticky', 'calls down', 'calldown', 'call multiple streets', 'wide calling range', 'calls too wide postflop', 'never folds')),
    ('WIDE_PREFLOP_CALL', ('wide calling', 'calls too wide', 'wide range pre', 'loose calling', 'wide preflop', 'wide entry', 'weaker/passive preflop')),
    ('REPEATED_LIMP', ('limp', 'open-limp', 'open limp', 'repeated limp')),
    ('WEAK_STAB', ('weak stab', 'stabs', 'probe weak', 'stab after')),
    ('FIT_OR_FOLD', ('fit-or-fold', 'fit or fold', 'gives up postflop', 'one-and-done')),
    ('SHOWDOWN_ONLY', ('at showdown', 'showed down', 'showdown only', 'shown at showdown')),
)

# complete, cue-aligned future-exploit sentences, one per cue family. Each references the SAME line,
# states an action/frequency adjustment, and carries a guardrail; none switches to an unrelated tendency.
_FUTURE_TEMPLATE = {
    'WIDE_PREFLOP_CALL':
        'When this player enters the pot by calling again, isolate wider for value and use a larger '
        'value-oriented size, then keep value-betting thinner across the streets; do not add unsupported '
        'bluffs merely because their preflop range is wide.',
    'REPEATED_LIMP':
        'When this player open-limps again, raise to isolate over the limp with a wider value range and a '
        'larger size, and keep barrelling for value postflop; do not start bluff-raising the limp just '
        'because they entered the pot passively.',
    'EXCESSIVE_FOLD':
        'When this player is in the blinds or is facing your steal again, keep widening your steal and '
        'continuation range to attack their over-folding; do not over-widen into the rare strong hands '
        'they will actually continue with.',
    'CALLING_STATION':
        'Against the same calling-station line, value-bet thinner and bet more streets for value while '
        'cutting your bluffs to almost zero; do not try to blow this player off the marginal made hands '
        'they call with.',
    'WIDE_FLAT_3BET':
        'When this player flat-calls a 3-bet out of position again, keep applying postflop pressure with '
        'a value-weighted barrelling range and size up; do not over-bluff into their wide, sticky, '
        'capped calling range.',
    'SMALL_DONK':
        'Against the same small or minimum donk-bet line, raise for thin value with your made hands and '
        'float wider in position; do not read the small sizing as a licence to always bluff-raise it.',
    'LARGE_DONK':
        'Against the same donk-bet lead into the field, raise your strong made hands and high-equity '
        'draws more often for value and fold out your air rather than floating; do not turn marginal '
        'showdown value into a bluff-raise.',
    'PASSIVE_THEN_RAISE':
        'When this passive profile suddenly bets or raises a later street again, overfold your one-pair '
        'bluff-catchers and continue only with strong value, unless the board texture or accumulated '
        'evidence supports enough bluffs in their range.',
    'OVERSIZED_BET':
        'Against the same oversized turn or river bet, fold your marginal bluff-catchers more often '
        'unless you hold a relevant blocker or have fresh evidence that materially raises this player\'s '
        'bluff frequency.',
    'UNDERBLUFFED_RIVER':
        'Against the same large or polarising river line, fold bluff-catchers without a blocker more '
        'often because this player\'s river aggression is value-heavy; only call down when blockers or '
        'new evidence raise the expected bluff rate.',
    'OVERBLUFFED_AGGR':
        'When this player fires the same aggressive line again, widen your call-downs and bluff-catch '
        'lighter to capture their excess bluffs; do not start raising for value and folding out the very '
        'bluffs you are trying to catch.',
    'WEAK_STAB':
        'When this player stabs the same small bet after the action checks to them, raise or float to '
        'attack the stab more often; do not give that small bet automatic credit for a made hand.',
    'EXCESSIVE_3BET':
        'When this player 3-bets or re-raises at the same spot again, widen your continuing range and '
        '4-bet or call down lighter to punish the inflated frequency; do not fold hands that are clearly '
        'ahead of their wide re-raising range.',
    'FIT_OR_FOLD':
        'When this player takes the same fit-or-fold line postflop again, c-bet a wider range for fold '
        'equity and barrel more turns; do not keep firing once they have shown they are continuing with '
        'genuine strength.',
    'SHOWDOWN_ONLY':
        'Record this showdown-derived tendency for later, but wait until the same read is available '
        'before the decision before you act on it; do not apply a showdown-only read to a hand that is '
        'still in progress.',
}

# archetype-level fallback lines (used ONLY when no specific cue family is supported). Each is a
# complete sentence and is intentionally generic about the line.
_ARCHETYPE_FALLBACK = {
    'nit': 'When this tight player shows real aggression in a future hand, give their bets and raises '
           'extra respect and fold your medium-strength hands, continuing mainly with strong value until '
           'you have actually seen them deviate from the tight baseline.',
    'aggress': 'When this aggressive player applies the same pressure again, widen your continuing and '
               'call-down range to capture their extra bluffs, and do not fold out their bluffs by '
               'turning your bluff-catchers into raises.',
    'passive': 'When this loose-passive player takes the same passive line again, lean on thin value and '
               'larger value sizing while cutting your bluffs, and stay disciplined out of position '
               'without a real made hand.',
}

# action keywords each cue family's future exploit MUST contain at least one of (it addresses the cue),
# and conflicting-family exclusive markers it must NOT contain (it must not switch tendencies).
_FAMILY_REQUIRED = {
    'WIDE_PREFLOP_CALL': ('isolate', 'value'), 'REPEATED_LIMP': ('isolate', 'raise', 'value'),
    'EXCESSIVE_FOLD': ('steal', 'widen', 'wider', 'attack'), 'CALLING_STATION': ('value', 'thinner', 'more streets'),
    'WIDE_FLAT_3BET': ('pressure', 'barrel', 'value', 'size up'), 'SMALL_DONK': ('raise', 'thin value', 'float'),
    'LARGE_DONK': ('raise', 'value', 'draws'), 'PASSIVE_THEN_RAISE': ('overfold', 'fold', 'respect', 'strong value'),
    'OVERSIZED_BET': ('fold', 'bluff-catcher', 'blocker'), 'UNDERBLUFFED_RIVER': ('fold', 'bluff-catcher', 'blocker'),
    'OVERBLUFFED_AGGR': ('call', 'widen', 'bluff-catch', 'call-down'), 'WEAK_STAB': ('raise', 'float', 'attack'),
    'EXCESSIVE_3BET': ('widen', '4-bet', 'call', 'punish'), 'FIT_OR_FOLD': ('c-bet', 'barrel', 'fold equity'),
    'SHOWDOWN_ONLY': ('record', 'wait', 'available', 'note'), 'GENERIC': (),
}
# exclusive markers that, if present, indicate the future text belongs to a DIFFERENT (incompatible)
# tendency. Used by the alignment check to catch a future exploit swapped onto the wrong cue.
_FAMILY_EXCLUSIVE = {
    'PASSIVE_THEN_RAISE': ('overfold your one-pair', 'suddenly bets or raises', 'passive profile suddenly'),
    'LARGE_DONK': ('donk-bet lead into the field',), 'SMALL_DONK': ('small or minimum donk-bet',),
    'WIDE_PREFLOP_CALL': ('enters the pot by calling',), 'EXCESSIVE_FOLD': ('attack their over-folding',),
    'OVERBLUFFED_AGGR': ('capture their excess bluffs',), 'UNDERBLUFFED_RIVER': ('river aggression is value-heavy',),
}
# families whose action domains are mutually compatible (so a shared marker is not a contradiction).
_FAMILY_COMPATIBLE = {
    'WIDE_PREFLOP_CALL': ('REPEATED_LIMP', 'CALLING_STATION', 'WIDE_FLAT_3BET'),
    'REPEATED_LIMP': ('WIDE_PREFLOP_CALL',), 'CALLING_STATION': ('WIDE_PREFLOP_CALL', 'WIDE_FLAT_3BET'),
    'WIDE_FLAT_3BET': ('WIDE_PREFLOP_CALL', 'CALLING_STATION'),
    'OVERSIZED_BET': ('UNDERBLUFFED_RIVER', 'PASSIVE_THEN_RAISE'),
    'UNDERBLUFFED_RIVER': ('OVERSIZED_BET', 'PASSIVE_THEN_RAISE'),
    'PASSIVE_THEN_RAISE': ('OVERSIZED_BET', 'UNDERBLUFFED_RIVER'),
}

_FORBIDDEN_FUTURE = ('adjust in future.', 'exploit this tendency.', 'play accordingly.',
                     'be careful next time.', 'proceed cautiously.')
# trailing tokens that CANNOT validly end a complete English sentence -- if the canonical sentence ends
# on one of these (before its terminal punctuation) it was cut mid-clause. Deliberately MINIMAL: only
# articles, coordinating conjunctions, possessive determiners, the infinitival/genitive markers, and
# subordinators that demand a following clause. Stranded prepositions ("continue with."), object
# pronouns ("bluff-raise it.") and comparatives CAN legitimately end a sentence and are NOT listed. The
# primary truncation signal remains the MISSING terminal punctuation (the old word-clamp dropped it).
_DANGLING_TAIL = frozenset(
    'a an the and or but nor their your its his her our my to of '
    'because unless until while although whereas than'.split())


def _exploit_domain(exploit_now):
    """A coarse typed action domain for the CURRENT exploit -- used for provenance + compatibility."""
    t = (exploit_now or '').lower()
    if not t:
        return 'NONE'
    if 'isolate' in t or 'iso-raise' in t or 'iso raise' in t:
        return 'ISOLATE'
    if 'steal' in t or 'open wider' in t or 'steal wider' in t:
        return 'STEAL'
    if ('fold' in t or 'respect' in t) and 'value' not in t:
        return 'FOLD_RESPECT'
    if 'value-bet' in t or 'value bet' in t or 'thin value' in t or 'value-betting' in t:
        return 'VALUE_BET'
    if 'pressure' in t or 'barrel' in t:
        return 'PRESSURE'
    if 'call' in t and ('wider' in t or 'down' in t or 'lighter' in t):
        return 'CALL_WIDER'
    if 'trap' in t:
        return 'TRAP'
    if 'raise' in t and 'value' in t:
        return 'VALUE_RAISE'
    if 'raise' in t:
        return 'RAISE'
    return 'OTHER'


def _kw_match(pat, text):
    """Word-boundary keyword match with common inflection suffixes -- so 'nit' does NOT match inside
    'opportunity'/'rocket' (a leading word boundary blocks mid-word hits), but 'overfold' still matches
    'overfolds'/'overfolding' and 'nit' matches 'nitty'."""
    return re.search(r'(?<!\w)' + re.escape(pat) + r'(?:s|es|ed|ing|ty|y)?(?!\w)', text) is not None


def classify_cue_family(signal=None, cue=None, villain_did=None, action_ref=None, exploit_now=None):
    """Return the typed cue family for a lesson, CUE-FIRST: the structured atom signal wins; else the
    cue/observation/action text (word-boundary matched); else GENERIC. Never archetype-first."""
    sig = (signal or '').strip()
    if sig in _SIGNAL_CUE_FAMILY:
        return _SIGNAL_CUE_FAMILY[sig]
    text = ' '.join(str(x or '') for x in (cue, villain_did, action_ref, exploit_now)).lower()
    for fam, pats in _CUE_TEXT_FAMILY:
        if any(_kw_match(p, text) for p in pats):
            return fam
    return 'GENERIC'


def future_exploit_complete(text):
    """A complete teaching sentence: non-empty, opens with a capital, ends with terminal punctuation,
    carries no truncation marker or dangling tail, and is not a forbidden generic placeholder."""
    if not text:
        return False, 'empty'
    s = str(text).strip()
    if s.lower() in _FORBIDDEN_FUTURE:
        return False, 'forbidden_placeholder'
    if '…' in s or s.endswith('...') or s.rstrip().endswith('--'):
        return False, 'truncation_marker'
    if not s[0].isupper():
        return False, 'no_capital_start'
    if s[-1] not in '.!?':
        return False, 'no_terminal_punctuation'
    body = s[:-1].rstrip()
    last = body.split()[-1].strip('"\')') if body.split() else ''
    if last.lower() in _DANGLING_TAIL:
        return False, 'dangling_tail:%s' % last
    if len(s.split()) < 8:
        return False, 'too_short'
    return True, 'complete'


# phrases that justify a read with a later-street RESULT (hindsight) -- never allowed in a future exploit.
_HINDSIGHT_PHRASES = ('at showdown', 'showed down', 'because hero won', 'because hero lost',
                      'as it turned out', 'in hindsight', 'turned out to be', 'after we saw the showdown')


def cue_alignment(cue_family, future_text):
    """Does the future exploit address THIS cue family and not switch to an incompatible tendency?
    Deterministic: a required action token must be present; no exclusive marker of an incompatible
    family may appear; and no later-street/result (hindsight) justification."""
    fam = cue_family if cue_family in _FAMILY_REQUIRED else 'GENERIC'
    f = (future_text or '').lower()
    if any(h in f for h in _HINDSIGHT_PHRASES):
        return False, 'hindsight/result justification'
    req = _FAMILY_REQUIRED.get(fam, ())
    if req and not any(r in f for r in req):
        return False, 'missing required action for %s' % fam
    compat = set(_FAMILY_COMPATIBLE.get(fam, ())) | {fam}
    for other, markers in _FAMILY_EXCLUSIVE.items():
        if other in compat:
            continue
        if any(m in f for m in markers):
            return False, 'carries %s marker in a %s lesson' % (other, fam)
    return True, 'addresses %s; compatible action domain' % fam


def _future_from_current_exploit(exploit_now):
    """CURRENT_EXPLOIT_TRANSFORM: a complete future sentence built from the current exploit (used when
    the cue family is GENERIC but a concrete current exploit exists). Stays in the current domain."""
    base = (exploit_now or '').strip().rstrip('. ')
    if not base:
        return None
    return ('When this same read repeats in a future hand, apply the same adjustment proactively -- %s '
            '-- and stay within the guardrail until another data point confirms the tendency.'
            % (base[0].lower() + base[1:]))


def derive_future_exploit(obj):
    """CUE-FIRST future-exploit generation with provenance. Returns a dict:
        {future_exploit, future_exploit_source, cue_family, current_exploit_domain, alignment_reason}.
    Order: specific cue family template -> current-exploit transform -> archetype fallback. The returned
    sentence is COMPLETE (never word-sliced)."""
    cue_family = classify_cue_family(obj.get('signal'), obj.get('cue'), obj.get('villain_did'),
                                     obj.get('action_ref'), obj.get('exploit_now'))
    domain = _exploit_domain(obj.get('exploit_now'))
    # 1) specific cue family template
    tmpl = _FUTURE_TEMPLATE.get(cue_family)
    if tmpl:
        return {'future_exploit': tmpl, 'future_exploit_source': 'CUE_TEMPLATE',
                'cue_family': cue_family, 'current_exploit_domain': domain,
                'alignment_reason': 'cue-template for %s addresses the same line; %s domain' % (cue_family, domain)}
    # 2) current-exploit transform (GENERIC family but a concrete current exploit)
    transformed = _future_from_current_exploit(obj.get('exploit_now'))
    if transformed:
        return {'future_exploit': transformed, 'future_exploit_source': 'CURRENT_EXPLOIT_TRANSFORM',
                'cue_family': cue_family, 'current_exploit_domain': domain,
                'alignment_reason': 'no specific cue template; transformed the concrete current exploit (%s)' % domain}
    # 3) archetype fallback (last resort; only when it does not contradict the cue)
    a = (obj.get('archetype') or '').lower()
    for key in ('nit', 'aggress', 'passive'):
        if key in a or (key == 'aggress' and 'aggro' in a) or (key == 'passive' and ('loose' in a or 'fish' in a)):
            line = _ARCHETYPE_FALLBACK[key]
            return {'future_exploit': line, 'future_exploit_source': 'ARCHETYPE_FALLBACK',
                    'cue_family': cue_family, 'current_exploit_domain': domain,
                    'alignment_reason': 'no supported cue template or current exploit; archetype-level (%s) fallback' % key}
    line = _ARCHETYPE_FALLBACK['passive']
    return {'future_exploit': line, 'future_exploit_source': 'ARCHETYPE_FALLBACK',
            'cue_family': cue_family, 'current_exploit_domain': domain,
            'alignment_reason': 'no cue template, current exploit, or archetype match; generic value fallback'}


def _read_state_for(read_states, villain_key):
    return (read_states or {}).get(villain_key) or {}


def teaching_from_exploit(exp, read_states, atoms_by_villain, *,
                          population='online', pko_by_hand=None):
    """Build ONE teaching object from a stamped exploit_opportunity dict.

    Every villain-fact field is copied from an existing stamped field; missing
    fields become None (the renderer falls back). No values are synthesised.
    """
    vk = exp.get('villain_key', '')
    rs = _read_state_for(read_states, vk)
    read_label = exp.get('exploit_read_label') or ''
    read_source = exp.get('read_source') or ''
    hand_id = exp.get('hand_id', '')
    hero_idx = exp.get('action_index')
    if hero_idx is None:
        hero_idx = exp.get('hero_decision_index')
    avail = exp.get('available_before_action_index')

    evidence_count = int(rs.get('n_evidence') or len(atoms_by_villain.get(vk) or []))
    same_type = _same_type_count(atoms_by_villain, vk, read_label)
    no_hind = _no_hindsight(read_source, avail, hero_idx)
    conf = derive_confidence(read_source, evidence_count, same_type)
    if not no_hind:
        conf = 'low'  # hindsight-gated -> never an actionable exploit

    # source_truth evidence = strictly-prior hands for a cross-hand read.
    prior_hids = [h for h in (rs.get('evidence_hand_ids') or []) if h != hand_id]
    if read_source == 'same_hand_pivot':
        ev_atoms = [hand_id] if no_hind else []
    else:
        ev_atoms = prior_hids

    # Single-hand ceiling: a read built from <=1 distinct hand can never reach
    # medium/high confidence (one cue is a watch/future note, not a stable tag).
    _unique_hands = 1 if read_source == 'same_hand_pivot' else len(set(prior_hids))
    if _unique_hands <= 1 and conf in ('medium', 'high'):
        conf = 'low'

    detector = exp.get('exploit_detector', '')
    baseline_source = _baseline_source(detector)
    warnings = []
    # cue EXPLAINS the behaviour; if it only restates the read label it is dropped.
    archetype = (exp.get('exploit_read_display')
                 or read_label or _clean(rs.get('primary_read')) or 'Unknown')
    cue_raw = _clean(exp.get('suggests'))
    cue = (cue_raw + _population_suffix(population)) if cue_raw else None
    if cue and not _cue_is_explanatory(cue, archetype):
        cue = None
        warnings.append('cue_not_explanatory')
    # ICM is a coarse caution for variance-increasing advice (no risk premium).
    icm = _ICM_CAUTION if _is_risky_exploit(detector, exp.get('so_what')) else None
    if icm:
        warnings.append('icm_pressure_unknown')
    # Cross-axis cue/read split -> compact node-specific caveat (confidence-tiered).
    # A genuine multi-axis AGGREGATE profile (split/mixed, emitted by
    # _build_read_states) dominates; a 'consistent' aggregate is NOT passed as an
    # override, so this hand's node-specific cue can still be flagged.
    prof_label, prof_caveat = derive_profile(
        _AXIS_BY_DETECTOR.get(detector), None, archetype,
        _aggregate_profile_override(rs), read_conf=conf)

    street = (exp.get('hero_decision_street') or '').strip() or 'preflop'
    _pko = _pko_subobject(pko_by_hand, hand_id)
    obj = {
        'villain_id': vk,
        'villain_alias': rs.get('villain_alias') or exp.get('villain_alias', ''),
        'street': street,
        'action_ref': exp.get('hero_action', '') or exp.get('exploit_detector', ''),
        'signal': '',                              # exploit objects classify cue family from the cue text
        'villain_did': _clean(exp.get('evidence_text')),
        'cue': cue,
        'archetype': archetype,
        'confidence': conf,
        'evidence_count': evidence_count,
        # actionable copy only when the read was known before the decision
        'exploit_now': _clean(exp.get('so_what')) if no_hind else None,
        'future_exploit': _clean(exp.get('recommended_exploit')) if no_hind else None,
        'do_not_overadjust': derive_do_not_overadjust(conf, read_label, bool(_pko)),
        'baseline_source': baseline_source,
        'profile_label': prof_label,
        'profile_caveat': prof_caveat,
        'icm_guardrail': icm,
        'source_warnings': warnings,
        # v8.17 Step-3: the producer's gradable predicate reason (factual-moment
        # copy when a graded missed/good is not warranted). '' when gradable.
        'non_gradable_reason': exp.get('non_gradable_reason', '')
        if not exp.get('gradable') else '',
        '_detector_outcome': exp.get('exploit_outcome') or exp.get('auto_verdict') or '',
        'source_truth': {
            'evidence_atoms': ev_atoms,
            'decision_id': '%s|%s|%s' % (hand_id, street,
                                         hero_idx if hero_idx is not None else '?'),
            'no_hindsight': no_hind,
        },
        'population': population,
        'kind': 'exploit',
        'fallback': False,
    }
    if _pko:
        obj['pko'] = _pko
    # thin / hindsight-gated -> downgrade to review note
    if conf == 'low' and (not no_hind or evidence_count <= 1):
        obj['fallback'] = True
        obj['exploit_now'] = None
        obj['future_exploit'] = None
    return _finalize(obj)


def teaching_from_atom(atom, read_states, atoms_by_villain, *,
                       signal_coaching, population='online', pko_by_hand=None):
    """Build ONE evidence-note teaching object from a raw evidence atom (a cue
    with no exploit verdict). Used for villain_evidence contexts."""
    vk = atom.get('villain_key', '')
    rs = _read_state_for(read_states, vk)
    signal = atom.get('signal', '')
    coach = (signal_coaching or {}).get(signal, {})
    hand_id = atom.get('hand_id', '')
    avail = atom.get('available_before_action_index')
    if avail is None:
        avail = atom.get('available_before')
    # rev-2 (Blocker 4): an evidence-note atom is only no-hindsight when it was
    # actionable in THIS hand (same_hand_actionable) AND carries an availability
    # index. Cross-hand aggregates and showdown-leaked atoms (available None or
    # not same-hand-actionable) degrade to a review-note fallback — they can
    # never present as an actionable same-hand cue.
    no_hind = bool(atom.get('same_hand_actionable')) and (avail is not None)

    evidence_count = int(rs.get('n_evidence') or len(atoms_by_villain.get(vk) or []))
    _pko = _pko_subobject(pko_by_hand, hand_id)
    _archetype = _clean(rs.get('primary_read')) or 'Unknown'
    _cue_raw = _clean(atom.get('suggests') or coach.get('suggests'))
    _cue = (_cue_raw + _population_suffix(population)) if _cue_raw else None
    _warnings = []
    if _cue and not _cue_is_explanatory(_cue, _archetype):
        _cue = None
        _warnings.append('cue_not_explanatory')
    _so_what = atom.get('so_what') or coach.get('so_what')
    _icm = _ICM_CAUTION if _is_risky_exploit('', _so_what) else None
    if _icm:
        _warnings.append('icm_pressure_unknown')
    # Cross-axis cue/read split (e.g. loose-passive entry cue vs an Aggressive
    # aggregate read) -> node-specific "Mixed profile" caveat before the read.
    _prof_label, _prof_caveat = derive_profile(
        _AXIS_BY_SIGNAL.get(signal), _CUE_NODE_BY_SIGNAL.get(signal),
        _archetype, _aggregate_profile_override(rs),
        read_conf=rs.get('confidence', 'low'))
    obj = {
        'villain_id': vk,
        'villain_alias': rs.get('villain_alias') or atom.get('villain_alias', ''),
        'street': (atom.get('street') or '').strip() or 'preflop',
        'action_ref': atom.get('villain_action', '') or signal,
        'signal': signal,                          # v8.18.1: structured cue key for cue-first generation
        'villain_did': _clean(atom.get('evidence_text')),
        'cue': _cue,
        'archetype': _archetype,
        'confidence': rs.get('confidence', 'low'),
        'evidence_count': evidence_count,
        'exploit_now': _clean(atom.get('so_what') or coach.get('so_what')) if no_hind else None,
        'future_exploit': None,  # pure evidence note carries no concrete next-time line
        'do_not_overadjust': derive_do_not_overadjust(
            rs.get('confidence', 'low'), rs.get('primary_read', ''), bool(_pko)),
        'baseline_source': 'none',       # evidence atoms are never grade-backed
        'profile_label': _prof_label,
        'profile_caveat': _prof_caveat,
        'icm_guardrail': _icm,
        'source_warnings': _warnings,
        'non_gradable_reason': 'evidence_note',  # cues are never graded outcomes
        '_detector_outcome': '',
        'source_truth': {
            'evidence_atoms': [hand_id],
            'decision_id': '%s|%s|%s' % (hand_id, atom.get('street', ''),
                                         atom.get('action_index', '?')),
            'no_hindsight': no_hind,
        },
        'population': population,
        'kind': 'evidence',
        'fallback': False,
    }
    pko = _pko_subobject(pko_by_hand, hand_id)
    if pko:
        obj['pko'] = pko
    if obj['confidence'] == 'low' or evidence_count <= 1 or not no_hind:
        # a single cue is a review candidate, not a mandate
        if evidence_count <= 1 or not no_hind:
            obj['fallback'] = True
            obj['exploit_now'] = None
    return _finalize(obj)


_CONF_RANK = {'high': 3, 'medium': 2, 'low': 1}


def _best_obj(objs):
    """The strongest teaching object for a villain: prefer non-fallback, then
    higher confidence, then more evidence, then one carrying an exploit. Pure +
    deterministic (no time/random)."""
    def _key(o):
        return (0 if o.get('fallback') else 1,
                _CONF_RANK.get(o.get('confidence'), 0),
                int(o.get('evidence_count') or 0),
                1 if o.get('exploit_now') else 0)
    return sorted(objs, key=_key, reverse=True)[0]


def build_villain_evidence_summary(teaching_by_villain, *, max_aliases=3):
    """Compact per-villain evidence roll-up (Slice D, secondary view).

    Groups already-built teaching objects by their STABLE villain id (the read
    key), NOT by alias — aliases are display-only and can change between hands.
    Returns a deterministic list of rows (one per villain), each cell read off
    the strongest object for that villain. Invents nothing; hindsight-gated /
    fallback-only villains summarise honestly (Unsure tag, '—' exploit). The
    alias list is truncated to ``max_aliases`` with a '+N more' suffix so a long
    seat history never overflows a compact row.
    """
    rows = []
    for vk, raw in (teaching_by_villain or {}).items():
        objs = [o for o in (raw or []) if o]
        if not objs:
            continue
        best = _best_obj(objs)
        aliases = []
        for o in objs:
            al = (o.get('villain_alias') or '').strip()
            if al and al not in aliases:
                aliases.append(al)
        alias_disp = ', '.join(aliases[:max_aliases])
        if len(aliases) > max_aliases:
            alias_disp += ' +%d more' % (len(aliases) - max_aliases)
        tag = best.get('tag_suggestion') or {}
        rows.append({
            'villain_id': vk,
            'alias': alias_disp or (best.get('villain_alias') or 'Unknown'),
            'alias_count': len(aliases),
            'archetype': best.get('archetype') or 'Unknown',
            'confidence': best.get('confidence') or 'low',
            'evidence_count': int(best.get('evidence_count') or 0),
            'cue': best.get('cue') or '',
            'tag_label': tag.get('label') or _N8_TAG_UNSURE[0],
            'tag_color': tag.get('color') or _N8_TAG_UNSURE[1],
            'exploit': best.get('exploit_now') or '—',
            'n_objects': len(objs),
            'actionable': bool(best.get('exploit_now')) and not best.get('fallback'),
        })
    rows.sort(key=lambda r: (-_CONF_RANK.get(r['confidence'], 0),
                             -r['evidence_count'], r['villain_id']))
    return rows


def build_villain_teaching(villain_intel, *, population='online', pko_by_hand=None):
    """Public entry. Project villain_intel into render-facing teaching objects.

    Returns {'teaching_by_hand': {hand_id: [obj, ...]},
             'teaching_by_villain': {villain_key: [obj, ...]},
             'teaching_summary': [row, ...],   # per-stable-villain roll-up
             'population': population}.
    Never raises on partial data — missing pieces degrade to fallbacks.
    """
    vi = villain_intel or {}
    read_states = vi.get('read_states') or {}
    atoms_by_villain = vi.get('atoms_by_villain') or {}
    exploits_by_hand = vi.get('exploits_by_hand') or {}
    atoms_by_hand = vi.get('atoms_by_hand') or {}
    # canonical signal coaching map (read-only import; fall back to {} if absent)
    try:
        from gem_villain_intel import SIGNAL_COACHING as _SIG
    except Exception:
        _SIG = {}

    by_hand = {}
    by_villain = {}

    def _emit(hand_id, obj):
        by_hand.setdefault(hand_id, []).append(obj)
        by_villain.setdefault(obj['villain_id'], []).append(obj)

    # 1) exploit-driven teaching objects (primary)
    covered = set()  # (hand_id, villain_key) already taught by an exploit
    for hand_id, exps in exploits_by_hand.items():
        for exp in (exps or []):
            obj = teaching_from_exploit(exp, read_states, atoms_by_villain,
                                        population=population, pko_by_hand=pko_by_hand)
            _emit(hand_id, obj)
            covered.add((hand_id, exp.get('villain_key', '')))

    # 2) evidence-note objects for actionable atoms with no exploit on that hand
    for hand_id, atoms in atoms_by_hand.items():
        seen = set()  # dedupe (villain, signal) per hand
        for atom in (atoms or []):
            vk = atom.get('villain_key', '')
            if (hand_id, vk) in covered:
                continue
            if not atom.get('hero_involved'):
                continue  # only teach cues relevant to a Hero decision
            key = (vk, atom.get('signal', ''))
            if key in seen:
                continue
            seen.add(key)
            obj = teaching_from_atom(atom, read_states, atoms_by_villain,
                                     signal_coaching=_SIG, population=population,
                                     pko_by_hand=pko_by_hand)
            _emit(hand_id, obj)

    return {'teaching_by_hand': by_hand, 'teaching_by_villain': by_villain,
            'teaching_summary': build_villain_evidence_summary(by_villain),
            'population': population}
