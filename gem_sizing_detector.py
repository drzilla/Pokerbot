"""GEM v8.20 Wave 1A — bet-sizing detector v1 (bounded, production-connected).

This WRAPS the existing production flop-c-bet sizing engine (gem_textures.aggregate_compliance, run
every session into stats['texture_gto_findings']) — it does NOT re-implement sizing math or invent a
generic standard. The reference is the curated gto_texture_archetypes.json sizings_pct band per
archetype × side × depth (sourced from real coaching sessions), so a finding never reduces to a vague
"differs from standard".

Family: flop_cbet_sizing. It emits an AGGREGATE LEAK signal (a repeated sizing pattern), NOT a per-hand
mistake verdict — a single off-size c-bet is never auto-graded as an error. Contributing hands are
listed as evidence; the analyst decides whether any individual hand was actually a mistake.

A signal fires ONLY for a high-confidence bucket:
  - sample_size_label == 'sufficient' (>= 8 c-bet opportunities), AND
  - sizing_judged_n >= MIN_JUDGED (enough sized c-bets to trust the rate), AND
  - sizing_compliance_pct < COMPLIANCE_FLOOR  (the off-reference rate is high).
Thin / small-sample / compliant buckets are excluded (and counted, never silently dropped).
"""

import gem_textures

MIN_JUDGED = 3
COMPLIANCE_FLOOR = 60.0

# ── v8.21 per-hand flop c-bet sizing assessment (pilot Family A) ──────────────────────────────
# Per-DECISION complement to the aggregate leak signal above: one assessment per individual flop
# c-bet, judged against the SAME canonical band (gem_textures get_gto_target / sizing_within_target).
# It re-implements no sizing math: the chosen % of pot is CONSUMED from hand['hero_bets'] (the field
# gem_analyzer feeds to aggregate_compliance); the band and the deviation test are canonical owners.
TOLERANCE_PP = 10        # within +/-10pp of a sanctioned size = compliant (canonical default tolerance)
GROSS_PP = 25            # a deviation this large (percentage points) is beyond a plausible mixing artifact
GROSS_OVER_MULT = 2.0    # actual >= 2x the largest sanctioned size  -> a clear over-size
GROSS_UNDER_MULT = 0.5   # actual <= 0.5x the smallest sanctioned size -> a clear under-size


def _arch_human(arch):
    return str(arch or '').replace('_', ' ')


def _depth_repr(depth_band):
    """A representative effective stack (the band low bound) for the reference lookup."""
    try:
        return max(int(str(depth_band).split('-')[0].replace('BB', '')), 1)
    except (ValueError, AttributeError):
        return 40


def _pattern_label(arch, side):
    """Human-readable pattern name (never an internal detector code)."""
    return 'Flop c-bets off-size on %s boards (%s)' % (_arch_human(arch), (side or '').upper())


def build_sizing_leak_signals(texture_gto_findings, *, min_judged=MIN_JUDGED,
                              compliance_floor=COMPLIANCE_FLOOR):
    """Return {'signals': [...], 'excluded_counts': {...}}. Each signal exposes detector family, the
    specific trigger, the evidence used, confidence, signal_type (aggregate_leak), the contributing
    hands, the exclusions considered, and the human what/why/adjustment for the report surface."""
    signals = []
    excluded = {'thin_sample': 0, 'small_sample': 0, 'compliant': 0, 'no_target': 0}
    for arch in sorted((texture_gto_findings or {}).keys()):
        sides = texture_gto_findings.get(arch) or {}
        for side in sorted(sides.keys()):
            d = sides.get(side)
            if not isinstance(d, dict):
                continue
            ssl = d.get('sample_size_label')
            comp = d.get('sizing_compliance_pct')
            judged = d.get('sizing_judged_n') or 0
            if comp is None:
                excluded['no_target'] += 1
                continue
            if ssl == 'small':
                excluded['small_sample'] += 1
                continue
            if ssl == 'thin' or judged < min_judged:
                excluded['thin_sample'] += 1
                continue
            if comp >= compliance_floor:
                excluded['compliant'] += 1
                continue
            # ── qualifying high-confidence aggregate sizing leak ──────────────
            sized = d.get('sizing_hands') or []
            off_ids, actual = [], []
            for h in sized:
                if isinstance(h, dict) and h.get('within') is False and h.get('id'):
                    off_ids.append(h['id'])
                    if h.get('sizing_pct') is not None:
                        actual.append(round(float(h['sizing_pct'])))
            depth = _depth_repr(sized[0].get('depth_band') if sized else None)
            tgt = gem_textures.get_gto_target(arch, side, depth) or {}
            ref = list(tgt.get('sizings_pct') or [])
            ref_str = ('/'.join('%d%%' % r for r in ref) if ref else 'reference')
            act_str = ', '.join('%d%%' % a for a in sorted(set(actual))[:6]) or '?'
            signals.append({
                'family': 'flop_cbet_sizing',
                'signal_type': 'aggregate_leak',                  # repeated leak, NOT a per-hand verdict
                'archetype': arch,
                'side': side,
                'pattern_label': _pattern_label(arch, side),
                'trigger': ('flop c-bet sizing off-reference on %d of %d sized c-bets '
                            '(%.0f%% within ±10pp of %s) on %s boards %s'
                            % (len(set(off_ids)), judged, comp, ref_str, _arch_human(arch), side.upper())),
                'evidence': {
                    'actual_sizings_pct': sorted(set(actual)),
                    'reference_sizings_pct': ref,
                    'tolerance_pp': 10,
                    'sizing_compliance_pct': comp,
                    'judged_c_bets': judged,
                    'sample_size_label': ssl,
                    'depth_band': (sized[0].get('depth_band') if sized else None),
                },
                'confidence': 'high',
                'contributing_hands': sorted(set(off_ids)),
                'exclusions_considered': 'thin / small-sample / compliant buckets excluded; structural '
                                         'eligibility owned by is_legal_cbet_opportunity',
                'requires_analyst_review': ('aggregate sizing pattern — analyst confirms whether any '
                                            'contributing hand was an individual mistake; the signal does '
                                            'not grade hands'),
                # human-readable surface copy (no internal codes)
                'what_happened': 'Hero c-bet %s on %s boards %s; the reference band is %s.'
                                 % (act_str, _arch_human(arch), side.upper(), ref_str),
                'why_it_matters': 'A repeated off-reference flop c-bet size leaks value or protection '
                                  'across this whole board class, not just one hand.',
                'adjustment': 'On %s boards %s, size flop c-bets toward %s.'
                              % (_arch_human(arch), side.upper(), ref_str),
            })
    return {'signals': signals, 'excluded_counts': excluded}


def _flop_cbet_sizing_pct(hand):
    """The canonical flop c-bet size (% of pot) Hero chose, CONSUMED from hand['hero_bets']
    (the same per-hand field gem_analyzer feeds to gem_textures.aggregate_compliance). Returns None
    when Hero did not c-bet the flop or the size is unparseable."""
    for b in (hand.get('hero_bets') or []):
        if isinstance(b, (list, tuple)) and len(b) >= 3 and b[0] == 'flop' and b[2] == 'cbet':
            try:
                return float(b[1])
            except (TypeError, ValueError):
                return None
    return None


def assess_flop_cbet_sizing(hand, *, tolerance_pp=TOLERANCE_PP, gross_pp=GROSS_PP):
    """Per-hand flop c-bet SIZING assessment vs the canonical board-archetype band
    (gto_texture_archetypes.json via gem_textures). Returns an assessment dict ONLY when Hero's flop
    c-bet size deviates from an APPLICABLE, COMPLETE band; otherwise returns None (fail closed).

    No parallel math: the chosen % of pot is consumed from hand['hero_bets']; the board archetype is the
    parser-stamped canonical field (fallback: the same gem_textures.classify_archetype owner); the band
    and the deviation test are gem_textures.get_gto_target / sizing_within_target. The result is
    result-independent (no runout / showdown / net).

    severity:
      'gross'    -> deviation_pp >= gross_pp AND (actual >= 2x the largest, or <= 0.5x the smallest,
                    sanctioned size) AND a single-target (non-dual) COMPLETE band -> a sizing ERROR.
      'moderate' -> outside tolerance but not gross, or a dual-strategy band      -> analyst-judged.

    Returns None (no candidate, fail closed) when ANY of: Hero is not the preflop aggressor; Hero did
    not c-bet the flop; fewer than 3 board cards; archetype unknown; chart confidence != 'complete';
    no applicable depth band; band empty; the size is within tolerance; or the comparison is unjudgeable.
    """
    if not hand.get('pfr'):
        return None
    actual = _flop_cbet_sizing_pct(hand)
    if actual is None:
        return None
    board = (hand.get('board') or [])[:3]
    if len(board) < 3:
        return None
    # canonical archetype: prefer the parser-stamped field, fall back to the SAME canonical owner.
    arch = hand.get('board_archetype') or ''
    if not arch or arch == 'unknown':
        arch = gem_textures.classify_archetype(board)
    if not arch or arch == 'unknown':
        return None
    meta = gem_textures.archetype_meta(arch) or {}
    if meta.get('confidence') != 'complete':
        return None                                   # fail closed on a non-complete chart
    side = 'ip' if hand.get('hero_ip') else 'oop'
    depth = hand.get('eff_stack_bb') or hand.get('stack_bb') or 100   # same depth source as the aggregate path
    try:
        depth = float(depth)
    except (TypeError, ValueError):
        return None
    tgt = gem_textures.get_gto_target(arch, side, depth)
    if not tgt or not tgt.get('sizings_pct'):
        return None                                   # no applicable band -> cannot judge -> fail closed
    targets = [float(t) for t in tgt['sizings_pct']]
    within = gem_textures.sizing_within_target(actual, targets, tolerance_pp)
    if within is None or within is True:
        return None                                   # unjudgeable or compliant -> no candidate
    # --- a real off-band deviation: classify severity ---
    nearest = min(targets, key=lambda t: abs(actual - t))
    deviation_pp = round(abs(actual - nearest), 1)
    direction = 'over' if actual > nearest else 'under'
    dual = bool(tgt.get('dual_strategy'))
    gross = (deviation_pp >= gross_pp and not dual
             and (actual >= GROSS_OVER_MULT * max(targets) or actual <= GROSS_UNDER_MULT * min(targets)))
    severity = 'gross' if gross else 'moderate'
    return {
        'family': 'flop_cbet_sizing',
        'board_archetype': arch,
        'cbet_side': side,
        'depth_band': tgt['depth_band'],
        'eff_stack_bb_flop': round(depth, 1),
        'actual_sizing_pct': round(actual, 1),
        'target_sizings_pct': [int(t) if float(t).is_integer() else round(t, 1) for t in targets],
        'nearest_target_pct': int(nearest) if float(nearest).is_integer() else round(nearest, 1),
        'deviation_pp': deviation_pp,
        'direction': direction,
        'tolerance_pp': tolerance_pp,
        'dual_strategy': dual,
        'chart_confidence': meta.get('confidence'),
        'chart_freq_pct': tgt.get('freq_pct'),
        'chart_notes': (tgt.get('notes') or '')[:240],
        'chart_source': 'gto_texture_archetypes.json (%s)' % (meta.get('source') or 'Dave sessions'),
        'severity': severity,
        'proposed_sizing_pct': int(nearest) if float(nearest).is_integer() else round(nearest, 1),
    }
