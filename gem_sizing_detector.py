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

# ── v8.21 flop c-bet sizing -> AGGREGATE leak summary (deep-validation recalibration) ─────────
# The per-hand sizing assessment below found 0 confirmed mistakes across 3,609 real hands, so it is NOT
# wired into the per-hand analyst queue. Instead `assess_flop_cbet_sizing` (with all safety gates: SRP-only,
# heads-up, non-all-in, within-band-spread compliant) is the INPUT to `summarize_offband_sizing`, an
# aggregate coaching-leak rollup (counts/rates by texture/side/depth/direction; representative hands are
# EXAMPLES, never confirmed mistakes; zero mandatory reviews). It re-implements no sizing math: the chosen
# % of pot is CONSUMED from hand['hero_bets']; the band + deviation test are canonical gem_textures owners.
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


def _flop_cbet_is_all_in(hand):
    """True iff Hero's flop c-bet action is all-in. An all-in c-bet is a commitment / stack-off
    decision, not a free sizing choice, so it is out of scope for a c-bet SIZING comparison."""
    for a in (hand.get('action_ledger') or []):
        if (isinstance(a, dict) and a.get('street') == 'flop' and a.get('player') == 'Hero'
                and (a.get('action') in ('bets', 'raises'))):
            return bool(a.get('is_all_in'))
    return False


def _chart_applies(hand):
    """The gto_texture_archetypes.json bands are calibrated for HEADS-UP, SINGLE-RAISED-POT range
    c-bets. The chart is NOT applicable to 3-bet/4-bet pots or multiway flops, so the detector must
    FAIL CLOSED there rather than judging an off-chart node against an inapplicable band. Returns
    (applies: bool, reason: str)."""
    if (hand.get('pot_type') or '') != 'SRP':
        return False, 'pot_type_not_srp'
    if hand.get('multiway_flop') or (hand.get('players_at_flop') or 2) > 2:
        return False, 'multiway_flop'
    if _flop_cbet_is_all_in(hand):
        return False, 'all_in_cbet'
    return True, ''


def applicable_band(hand):
    """Chart-applicable flop c-bet OPPORTUNITY descriptor, or None. Encapsulates every safety gate so the
    chart is only ever consulted where it actually holds: Hero is the preflop aggressor, the pot is
    SINGLE-RAISED, the flop is HEADS-UP, the c-bet is NOT all-in, >=3 board cards, a classified archetype,
    a COMPLETE chart, and an applicable depth band. Uses only canonical decision-time inputs (no results /
    showdown / range / equity). Returns a dict (archetype, side, depth, band) when the hand is a judgeable
    opportunity, else None (fail closed)."""
    if not hand.get('pfr'):
        return None
    actual = _flop_cbet_sizing_pct(hand)
    if actual is None:
        return None
    applies, _why = _chart_applies(hand)         # HU single-raised-pot, non-all-in only
    if not applies:
        return None
    board = (hand.get('board') or [])[:3]
    if len(board) < 3:
        return None
    arch = hand.get('board_archetype') or ''     # canonical parser field, fallback to the same owner
    if not arch or arch == 'unknown':
        arch = gem_textures.classify_archetype(board)
    if not arch or arch == 'unknown':
        return None
    meta = gem_textures.archetype_meta(arch) or {}
    if meta.get('confidence') != 'complete':
        return None
    side = 'ip' if hand.get('hero_ip') else 'oop'
    depth = hand.get('eff_stack_bb') or hand.get('stack_bb') or 100
    try:
        depth = float(depth)
    except (TypeError, ValueError):
        return None
    tgt = gem_textures.get_gto_target(arch, side, depth)
    if not tgt or not tgt.get('sizings_pct'):
        return None
    return {'archetype': arch, 'side': side, 'depth_bb': round(depth, 1), 'depth_band': tgt['depth_band'],
            'targets': [float(t) for t in tgt['sizings_pct']], 'dual_strategy': bool(tgt.get('dual_strategy')),
            'actual_pct': float(actual), 'freq_pct': tgt.get('freq_pct'), 'notes': (tgt.get('notes') or '')[:240],
            'source': meta.get('source') or 'Dave sessions', 'chart_confidence': meta.get('confidence')}


def _classify_deviation(actual, targets, dual, *, tolerance_pp=TOLERANCE_PP, gross_pp=GROSS_PP):
    """(off_band, direction, nearest, deviation_pp, severity) for an actual size vs a sanctioned band.
    Compliant (off_band False) when within +/-tolerance of a sanctioned size OR within the [min,max]
    spread of a multi-size band (the band sanctions a spread; an in-between compromise size is not a
    deviation). 'gross' only when a single-target band is missed by >=gross_pp and >=2x/<=0.5x the band."""
    within = gem_textures.sizing_within_target(actual, targets, tolerance_pp)
    if within is None or within is True:
        return (False, None, None, None, None)
    if len(targets) >= 2 and min(targets) <= actual <= max(targets):
        return (False, None, None, None, None)
    nearest = min(targets, key=lambda t: abs(actual - t))
    deviation_pp = round(abs(actual - nearest), 1)
    direction = 'over' if actual > nearest else 'under'
    gross = (deviation_pp >= gross_pp and not dual
             and (actual >= GROSS_OVER_MULT * max(targets) or actual <= GROSS_UNDER_MULT * min(targets)))
    return (True, direction, nearest, deviation_pp, 'gross' if gross else 'moderate')


def assess_flop_cbet_sizing(hand, *, tolerance_pp=TOLERANCE_PP, gross_pp=GROSS_PP):
    """SAFE per-hand flop c-bet SIZING assessment vs the canonical band -- the INPUT to the aggregate
    summary (it is NOT wired into the per-hand analyst queue; see the deep-validation closeout). Returns an
    assessment dict only when Hero's c-bet deviates from an applicable COMPLETE band, else None (fail
    closed). No parallel math, no result/showdown/range/equity; severity is informational, never a verdict."""
    ab = applicable_band(hand)
    if ab is None:
        return None
    off, direction, nearest, deviation_pp, severity = _classify_deviation(
        ab['actual_pct'], ab['targets'], ab['dual_strategy'], tolerance_pp=tolerance_pp, gross_pp=gross_pp)
    if not off:
        return None
    _fmt = lambda t: int(t) if float(t).is_integer() else round(t, 1)
    return {
        'family': 'flop_cbet_sizing', 'pot_type': 'SRP', 'heads_up': True, 'all_in_cbet': False,
        'board_archetype': ab['archetype'], 'cbet_side': ab['side'], 'depth_band': ab['depth_band'],
        'eff_stack_bb_flop': ab['depth_bb'], 'actual_sizing_pct': round(ab['actual_pct'], 1),
        'target_sizings_pct': [_fmt(t) for t in ab['targets']], 'nearest_target_pct': _fmt(nearest),
        'deviation_pp': deviation_pp, 'direction': direction, 'tolerance_pp': tolerance_pp,
        'dual_strategy': ab['dual_strategy'], 'chart_confidence': ab['chart_confidence'],
        'chart_freq_pct': ab['freq_pct'], 'chart_notes': ab['notes'],
        'chart_source': 'gto_texture_archetypes.json (%s)' % ab['source'],
        'severity': severity, 'proposed_sizing_pct': _fmt(nearest),
    }


def _depth_tier(bb):
    if bb < 25:
        return '<25BB'
    if bb < 40:
        return '25-40BB'
    if bb < 100:
        return '40-100BB'
    return '100BB+'


def summarize_offband_sizing(hands, *, min_opps_for_leak=6, leak_rate_floor=0.5, dominant_floor=0.7,
                             examples_per_bucket=3):
    """AGGREGATE flop c-bet sizing-leak summary built from the SAFE per-hand assessments.

    This is the recalibrated home for the sizing signal: it emits NO per-hand analyst candidates, creates
    ZERO mandatory reviews, and labels NO individual hand a confirmed mistake. It counts opportunities and
    off-band rates by texture/side/depth/direction so a recurring sizing leak can be COACHED. Representative
    hands are EXAMPLES only. Uses only canonical decision-time inputs; fails closed where the chart does not
    apply (those hands are simply not opportunities). Returns a JSON-safe dict."""
    opps, offs = [], []
    for h in hands:
        ab = applicable_band(h)
        if ab is None:
            continue
        opps.append((h, ab))
        off, direction, nearest, dev_pp, severity = _classify_deviation(
            ab['actual_pct'], ab['targets'], ab['dual_strategy'])
        if off:
            offs.append((h, ab, {'direction': direction, 'deviation_pp': dev_pp, 'severity': severity}))

    def _b():
        return {'opps': 0, 'off': 0, 'under': 0, 'over': 0, 'examples': []}

    by_arch_side, by_side, by_depth, by_arch = {}, {}, {}, {}

    def _keys(ab):
        return ((('%s|%s' % (ab['archetype'], ab['side'])), by_arch_side), (ab['side'], by_side),
                (_depth_tier(ab['depth_bb']), by_depth), (ab['archetype'], by_arch))

    for _h, ab in opps:
        for key, d in _keys(ab):
            d.setdefault(key, _b())['opps'] += 1
    for h, ab, dev in offs:
        ex = {'hand_id': h.get('id'), 'session': h.get('_session'), 'board': (h.get('board') or [])[:3],
              'actual_pct': round(ab['actual_pct'], 1),
              'targets': [int(t) if float(t).is_integer() else round(t, 1) for t in ab['targets']],
              'direction': dev['direction'], 'deviation_pp': dev['deviation_pp']}
        for key, d in _keys(ab):
            b = d.setdefault(key, _b())
            b['off'] += 1
            b[dev['direction']] += 1
            if len(b['examples']) < examples_per_bucket:
                b['examples'].append(ex)

    def _rate(d):
        out = {}
        for k, b in sorted(d.items()):
            b = dict(b)
            b['off_band_rate'] = round(b['off'] / b['opps'], 3) if b['opps'] else 0.0
            out[k] = b
        return out

    by_arch_side, by_side, by_depth, by_arch = _rate(by_arch_side), _rate(by_side), _rate(by_depth), _rate(by_arch)

    leak_signals = []
    for key, b in by_arch_side.items():
        if b['opps'] < min_opps_for_leak or b['off_band_rate'] < leak_rate_floor or b['off'] == 0:
            continue
        dom_dir, dom_n = ('under', b['under']) if b['under'] >= b['over'] else ('over', b['over'])
        if dom_n / b['off'] < dominant_floor:
            continue
        arch, side = key.split('|')
        band = b['examples'][0]['targets'] if b['examples'] else None
        leak_signals.append({
            'pattern': 'flop c-bet %s-sizing on %s boards (%s)' % (dom_dir, arch.replace('_', ' '), side.upper()),
            'archetype': arch, 'side': side, 'opportunities': b['opps'], 'off_band': b['off'],
            'off_band_rate': b['off_band_rate'], 'dominant_direction': dom_dir,
            'dominant_share': round(dom_n / b['off'], 3), 'sanctioned_band_pct': band,
            'coaching': ('Hero %s-sized %d of %d c-bets (%.0f%%) on %s boards %s vs the sanctioned %s band; '
                         'move sizing toward the band.'
                         % (dom_dir, b['off'], b['opps'], 100 * b['off_band_rate'], arch.replace('_', ' '),
                            side.upper(), band)),
            'representative_hands': [e['hand_id'] for e in b['examples']],
            'note': 'aggregate coaching leak -- representative hands are EXAMPLES, not confirmed mistakes',
        })
    leak_signals.sort(key=lambda s: (-s['off_band'], -s['off_band_rate']))

    n_opp, n_off = len(opps), len(offs)
    return {
        'family': 'flop_cbet_sizing_aggregate', 'street': 'flop', 'pot_type': 'SRP',
        'table': 'heads_up', 'cbet_kind': 'non_all_in',
        'opportunities': n_opp, 'off_band': n_off, 'off_band_rate': round(n_off / n_opp, 3) if n_opp else 0.0,
        'under_sized': sum(1 for _h, _a, d in offs if d['direction'] == 'under'),
        'over_sized': sum(1 for _h, _a, d in offs if d['direction'] == 'over'),
        'by_archetype_side': by_arch_side, 'by_side': by_side, 'by_depth_band': by_depth,
        'by_archetype': by_arch, 'leak_signals': leak_signals,
        'creates_mandatory_analyst_reviews': 0, 'labels_confirmed_mistakes': False,
        'uses_results_or_equity': False,
    }
