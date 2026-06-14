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
"""

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

# Canonical exploit read-label -> the atom dimensions that CORROBORATE it.
# Used only to count same-decision-type evidence for confidence (no new scoring).
_READ_FAMILY_DIMS = {
    'Sticky Passive': {'sticky'},
    'Loose Passive': {'loose_passive'},
    'Nit / Rock': {'tight'},
    'Aggressive': {'aggressive', 'pivot'},
}

_WORD_CAP = {'villain_did': 22, 'exploit_now': 18, 'future_exploit': 18, 'cue': 24}


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


def _teach_lines(obj):
    """Pre-render the FULL compact teaching sequence in PYTHON so the renderer
    only displays strings (it cannot invent facts). rev-2: emits the whole
    sequence (Read header -> Villain -> Cue -> Now -> Next time -> Avoid
    over-adjusting -> Bounty) for non-fallback objects; a single fallback line
    for thin / hindsight-gated objects."""
    if obj.get('fallback'):
        return [FALLBACK_LINE]
    lines = []
    head = []
    if obj.get('archetype'):
        head.append(str(obj['archetype']))
    if obj.get('confidence'):
        head.append(str(obj['confidence']) + ' confidence')
    ec = obj.get('evidence_count')
    if isinstance(ec, int):
        head.append('%d cue%s' % (ec, '' if ec == 1 else 's'))
    if head:
        lines.append('Read: ' + ' · '.join(head))
    if obj.get('villain_did'):
        lines.append('Villain: ' + obj['villain_did'])
    if obj.get('cue'):
        lines.append('Cue: ' + obj['cue'])
    if obj.get('exploit_now'):
        lines.append('Now: ' + obj['exploit_now'])
    if obj.get('future_exploit'):
        lines.append('Next time: ' + obj['future_exploit'])
    if obj.get('do_not_overadjust'):
        lines.append('Avoid over-adjusting: ' + obj['do_not_overadjust'])
    pko = obj.get('pko')
    if pko and pko.get('cover_label'):
        lines.append('Bounty: ' + pko['cover_label'])
    return lines or [FALLBACK_LINE]


def _finalize(obj):
    """Apply word caps + attach pre-rendered teach_lines; stamp fallback."""
    obj['villain_did'] = _clamp_words(obj.get('villain_did'), _WORD_CAP['villain_did'])
    obj['cue'] = _clamp_words(obj.get('cue'), _WORD_CAP['cue'])
    obj['exploit_now'] = _clamp_words(obj.get('exploit_now'), _WORD_CAP['exploit_now'])
    obj['future_exploit'] = _clamp_words(obj.get('future_exploit'), _WORD_CAP['future_exploit'])
    # Fallback if there is no real villain_did/cue OR nothing actionable to say.
    thin = (not obj.get('villain_did') and not obj.get('cue'))
    if thin:
        obj['fallback'] = True
    obj['teach_lines'] = _teach_lines(obj)
    return obj


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

    street = (exp.get('hero_decision_street') or '').strip() or 'preflop'
    _pko = _pko_subobject(pko_by_hand, hand_id)
    obj = {
        'villain_id': vk,
        'villain_alias': rs.get('villain_alias') or exp.get('villain_alias', ''),
        'street': street,
        'action_ref': exp.get('hero_action', '') or exp.get('exploit_detector', ''),
        'villain_did': _clean(exp.get('evidence_text')),
        'cue': (_clean(exp.get('suggests')) + _population_suffix(population))
                if _clean(exp.get('suggests')) else None,
        'archetype': (exp.get('exploit_read_display')
                      or read_label or _clean(rs.get('primary_read')) or 'Unknown'),
        'confidence': conf,
        'evidence_count': evidence_count,
        # actionable copy only when the read was known before the decision
        'exploit_now': _clean(exp.get('so_what')) if no_hind else None,
        'future_exploit': _clean(exp.get('recommended_exploit')) if no_hind else None,
        'do_not_overadjust': derive_do_not_overadjust(conf, read_label, bool(_pko)),
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
    obj = {
        'villain_id': vk,
        'villain_alias': rs.get('villain_alias') or atom.get('villain_alias', ''),
        'street': (atom.get('street') or '').strip() or 'preflop',
        'action_ref': atom.get('villain_action', '') or signal,
        'villain_did': _clean(atom.get('evidence_text')),
        'cue': (_clean(atom.get('suggests') or coach.get('suggests')) + _population_suffix(population))
                if _clean(atom.get('suggests') or coach.get('suggests')) else None,
        'archetype': _clean(rs.get('primary_read')) or 'Unknown',
        'confidence': rs.get('confidence', 'low'),
        'evidence_count': evidence_count,
        'exploit_now': _clean(atom.get('so_what') or coach.get('so_what')) if no_hind else None,
        'future_exploit': None,  # pure evidence note carries no concrete next-time line
        'do_not_overadjust': derive_do_not_overadjust(
            rs.get('confidence', 'low'), rs.get('primary_read', ''), bool(_pko)),
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


def build_villain_teaching(villain_intel, *, population='online', pko_by_hand=None):
    """Public entry. Project villain_intel into render-facing teaching objects.

    Returns {'teaching_by_hand': {hand_id: [obj, ...]},
             'teaching_by_villain': {villain_key: [obj, ...]},
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
            'population': population}
