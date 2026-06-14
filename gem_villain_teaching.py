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
    lines.append('Read: ' + _candidate_archetype(obj.get('archetype'),
                                                  obj.get('confidence')))
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
    obj['future_exploit'] = _clamp_words(obj.get('future_exploit'), _WORD_CAP['future_exploit'])
    # Fallback if there is no real villain_did/cue OR nothing actionable to say.
    thin = (not obj.get('villain_did') and not obj.get('cue'))
    if thin:
        obj['fallback'] = True
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
